# AbletonMCP/init.py
from __future__ import absolute_import, print_function, unicode_literals

from _Framework.ControlSurface import ControlSurface
import Live
import socket
import json
import threading
import time
import traceback

# Change queue import for Python 2
try:
    import Queue as queue  # Python 2
except ImportError:
    import queue  # Python 3

# Constants for socket communication
DEFAULT_PORT = 9877
HOST = "localhost"

def create_instance(c_instance):
    """Create and return the AbletonMCP script instance"""
    return AbletonMCP(c_instance)

class AbletonMCP(ControlSurface):
    """AbletonMCP Remote Script for Ableton Live"""
    
    def __init__(self, c_instance):
        """Initialize the control surface"""
        ControlSurface.__init__(self, c_instance)
        self.log_message("AbletonMCP Remote Script initializing...")
        
        # Socket server for communication
        self.server = None
        self.client_threads = []
        self.server_thread = None
        self.running = False
        
        # Cache the song reference for easier access
        self._song = self.song()
        
        # Start the socket server
        self.start_server()
        
        self.log_message("AbletonMCP initialized")
        
        # Show a message in Ableton
        self.show_message("AbletonMCP: Listening for commands on port " + str(DEFAULT_PORT))
    
    def disconnect(self):
        """Called when Ableton closes or the control surface is removed"""
        self.log_message("AbletonMCP disconnecting...")
        self.running = False
        
        # Stop the server
        if self.server:
            try:
                self.server.close()
            except (OSError, socket.error):
                pass
        
        # Wait for the server thread to exit
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(1.0)
            
        # Clean up any client threads
        for client_thread in self.client_threads[:]:
            if client_thread.is_alive():
                # We don't join them as they might be stuck
                self.log_message("Client thread still alive during disconnect")
        
        ControlSurface.disconnect(self)
        self.log_message("AbletonMCP disconnected")
    
    def start_server(self):
        """Start the socket server in a separate thread"""
        try:
            self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server.bind((HOST, DEFAULT_PORT))
            self.server.listen(5)  # Allow up to 5 pending connections
            
            self.running = True
            self.server_thread = threading.Thread(target=self._server_thread)
            self.server_thread.daemon = True
            self.server_thread.start()
            
            self.log_message("Server started on port " + str(DEFAULT_PORT))
        except Exception as e:
            self.log_message("Error starting server: " + str(e))
            self.show_message("AbletonMCP: Error starting server - " + str(e))
    
    def _server_thread(self):
        """Server thread implementation - handles client connections"""
        try:
            self.log_message("Server thread started")
            # Set a timeout to allow regular checking of running flag
            self.server.settimeout(1.0)
            
            while self.running:
                try:
                    # Accept connections with timeout
                    client, address = self.server.accept()
                    self.log_message("Connection accepted from " + str(address))
                    self.show_message("AbletonMCP: Client connected")
                    
                    # Handle client in a separate thread
                    client_thread = threading.Thread(
                        target=self._handle_client,
                        args=(client,)
                    )
                    client_thread.daemon = True
                    client_thread.start()
                    
                    # Keep track of client threads
                    self.client_threads.append(client_thread)
                    
                    # Clean up finished client threads
                    self.client_threads = [t for t in self.client_threads if t.is_alive()]
                    
                except socket.timeout:
                    # No connection yet, just continue
                    continue
                except Exception as e:
                    if self.running:  # Only log if still running
                        self.log_message("Server accept error: " + str(e))
                    time.sleep(0.5)
            
            self.log_message("Server thread stopped")
        except Exception as e:
            self.log_message("Server thread error: " + str(e))
    
    def _handle_client(self, client):
        """Handle communication with a connected client"""
        self.log_message("Client handler started")
        client.settimeout(None)  # No timeout for client socket
        buffer = ''  # Changed from b'' to '' for Python 2
        
        try:
            while self.running:
                try:
                    # Receive data
                    data = client.recv(8192)
                    
                    if not data:
                        # Client disconnected
                        self.log_message("Client disconnected")
                        break
                    
                    # Accumulate data in buffer with explicit encoding/decoding
                    try:
                        # Python 3: data is bytes, decode to string
                        buffer += data.decode('utf-8')
                    except AttributeError:
                        # Python 2: data is already string
                        buffer += data
                    
                    try:
                        # Try to parse command from buffer
                        command = json.loads(buffer)  # Removed decode('utf-8')
                        buffer = ''  # Clear buffer after successful parse
                        
                        self.log_message("Received command: " + str(command.get("type", "unknown")))
                        
                        # Process the command and get response
                        response = self._process_command(command)
                        
                        # Send the response with explicit encoding
                        try:
                            # Python 3: encode string to bytes
                            client.sendall(json.dumps(response).encode('utf-8'))
                        except AttributeError:
                            # Python 2: string is already bytes
                            client.sendall(json.dumps(response))
                    except ValueError:
                        # Incomplete data, wait for more
                        continue
                        
                except Exception as e:
                    self.log_message("Error handling client data: " + str(e))
                    self.log_message(traceback.format_exc())
                    
                    # Send error response if possible
                    error_response = {
                        "status": "error",
                        "message": str(e)
                    }
                    try:
                        # Python 3: encode string to bytes
                        client.sendall(json.dumps(error_response).encode('utf-8'))
                    except AttributeError:
                        # Python 2: string is already bytes
                        client.sendall(json.dumps(error_response))
                    except (OSError, socket.error):
                        # Connection is probably dead — exit the loop
                        break
                    
                    # For serious errors, break the loop
                    if not isinstance(e, ValueError):
                        break
        except Exception as e:
            self.log_message("Error in client handler: " + str(e))
        finally:
            try:
                client.close()
            except (OSError, socket.error):
                pass
            self.log_message("Client handler stopped")
    
    def _process_command(self, command):
        """Process a command from the client and return a response"""
        command_type = command.get("type", "")
        params = command.get("params", {})
        
        # Initialize response
        response = {
            "status": "success",
            "result": {}
        }
        
        try:
            # Route the command to the appropriate handler
            if command_type == "get_session_info":
                response["result"] = self._get_session_info()
            elif command_type == "get_track_info":
                track_index = params.get("track_index", 0)
                response["result"] = self._get_track_info(track_index)
            elif command_type == "get_device_parameters":
                track_index = params.get("track_index", 0)
                device_index = params.get("device_index", 0)
                response["result"] = self._get_device_parameters(track_index, device_index)
            elif command_type == "get_device_parameter_value":
                track_index = params.get("track_index", 0)
                device_index = params.get("device_index", 0)
                parameter = params.get("parameter")
                response["result"] = self._get_device_parameter_value(track_index, device_index, parameter)
            # get_clip_notes must run on the main thread (LOM note reads require it)
            elif command_type == "get_return_track_info":
                return_index = params.get("return_index", 0)
                response["result"] = self._get_return_track_info(return_index)
            elif command_type == "get_track_routing":
                track_index = params.get("track_index", 0)
                response["result"] = self._get_track_routing(track_index)
            elif command_type == "get_arrangement_clips":
                track_index = params.get("track_index", 0)
                response["result"] = self._get_arrangement_clips(track_index)
            elif command_type == "get_full_session":
                include_params = params.get("include_params", True)
                response["result"] = self._get_full_session(include_params)
            elif command_type == "get_clip_envelope":
                track_index = params.get("track_index", 0)
                clip_index = params.get("clip_index", 0)
                param_path = params.get("param_path", "")
                sample_interval = params.get("sample_interval", 0.25)
                times = params.get("times")
                location = params.get("location", "session")
                response["result"] = self._get_clip_envelope(
                    track_index, clip_index, param_path, sample_interval, times, location)
            elif command_type == "get_parameter_automation_state":
                track_index = params.get("track_index", 0)
                device_index = params.get("device_index", 0)
                parameter = params.get("parameter")
                response["result"] = self._get_parameter_automation_state(
                    track_index, device_index, parameter)
            elif command_type == "get_master_device_parameters":
                device_index = params.get("device_index", 0)
                response["result"] = self._get_master_device_parameters(device_index)
            elif command_type == "get_return_device_parameters":
                return_index = params.get("return_index", 0)
                device_index = params.get("device_index", 0)
                response["result"] = self._get_return_device_parameters(
                    return_index, device_index)
            elif command_type == "get_rack_chains":
                track_index = params.get("track_index", 0)
                device_index = params.get("device_index", 0)
                response["result"] = self._get_rack_chains(track_index, device_index)
            elif command_type == "get_drum_pads":
                track_index = params.get("track_index", 0)
                device_index = params.get("device_index", 0)
                only_non_empty = params.get("only_non_empty", True)
                response["result"] = self._get_drum_pads(
                    track_index, device_index, only_non_empty)
            elif command_type == "get_song_scale":
                response["result"] = self._get_song_scale()
            elif command_type == "get_cue_points":
                response["result"] = self._get_cue_points()
            elif command_type == "get_grooves":
                response["result"] = self._get_grooves()
            elif command_type == "get_clip_warp":
                track_index = params.get("track_index", 0)
                clip_index = params.get("clip_index", 0)
                response["result"] = self._get_clip_warp(track_index, clip_index)
            elif command_type == "get_selection":
                response["result"] = self._get_selection()
            elif command_type == "get_transport_state":
                response["result"] = self._get_transport_state()
            elif command_type == "get_scenes":
                response["result"] = self._get_scenes()
            elif command_type == "get_available_routings":
                response["result"] = self._get_available_routings(
                    params.get("track_index", 0))
            elif command_type == "get_clip_settings":
                response["result"] = self._get_clip_settings(
                    params.get("track_index", 0),
                    params.get("clip_index", 0))
            elif command_type == "get_warp_markers":
                response["result"] = self._get_warp_markers(
                    params.get("track_index", 0),
                    params.get("clip_index", 0))
            # These commands must run on the main thread (writes + note reads)
            elif command_type in ["get_clip_notes",
                                 "create_midi_track", "set_track_name",
                                 "create_clip", "add_notes_to_clip", "set_clip_name",
                                 "set_tempo", "fire_clip", "stop_clip",
                                 "start_playback", "stop_playback", "load_browser_item",
                                 "set_device_parameter", "set_mixer_value",
                                 "set_arrangement_loop", "clear_clip_envelope",
                                 # Tier 1
                                 "duplicate_track", "delete_track", "undo", "redo",
                                 "capture_midi", "stop_all_clips", "create_audio_track",
                                 # Tier 2
                                 "delete_device", "move_device", "set_return_mixer_value",
                                 "set_track_routing", "set_track_state",
                                 # Tier 3
                                 "delete_arrangement_clip", "set_clip_loop_region",
                                 "jump_to_beat",
                                 # Clip envelope writes
                                 "set_clip_envelope_point", "set_clip_envelope_curve",
                                 "re_enable_automation",
                                 # Rack chain / drum pad writes
                                 "set_chain_state", "set_chain_mixer_value",
                                 "set_drum_pad_state",
                                 # Master / return device parameter writes
                                 "set_master_device_parameter",
                                 "set_return_device_parameter",
                                 # Master / return chain mutations (2026-05-17)
                                 "load_master_item", "load_return_item",
                                 "create_return_track",
                                 # Live.Conversions wrappers (2026-05-17)
                                 "audio_to_midi_clip",
                                 "create_drum_rack_from_audio_clip",
                                 "create_midi_track_from_audio_clip",
                                 "move_track_devices_to_drum_pad",
                                 "convert_sliced_simpler_to_drum_rack",
                                 # High-value 6 writes (2026-05-17)
                                 "set_song_scale", "quantize_clip_notes",
                                 "set_or_delete_cue", "jump_to_cue",
                                 "delete_cue_by_index",
                                 "set_groove_params", "assign_groove_to_clip",
                                 "set_clip_warping", "set_warp_mode",
                                 "set_selection",
                                 # Transport batch (2026-05-17)
                                 "set_metronome", "set_count_in",
                                 "set_record_quantization", "set_time_signature",
                                 "set_session_record", "set_punch_region",
                                 "tap_tempo", "bump_tempo",
                                 # Scenes batch (2026-05-17)
                                 "create_scene", "delete_scene",
                                 "duplicate_scene", "capture_and_insert_scene",
                                 "set_scene_props", "fire_scene",
                                 # Track-state extras (2026-05-17)
                                 "set_track_monitoring", "set_track_freeze",
                                 "set_track_color", "set_track_fold",
                                 # Clip details (2026-05-17)
                                 "set_clip_color", "set_clip_gain",
                                 "set_clip_pitch", "set_clip_launch_settings",
                                 "set_clip_follow_action",
                                 # Warp markers (2026-05-17)
                                 "add_warp_marker", "remove_warp_marker",
                                 "move_warp_marker"]:
                # Use a thread-safe approach with a response queue
                response_queue = queue.Queue()
                
                # Define a function to execute on the main thread
                def main_thread_task():
                    try:
                        result = None
                        if command_type == "get_clip_notes":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            result = self._get_clip_notes(track_index, clip_index)
                        elif command_type == "create_midi_track":
                            index = params.get("index", -1)
                            result = self._create_midi_track(index)
                        elif command_type == "set_track_name":
                            track_index = params.get("track_index", 0)
                            name = params.get("name", "")
                            result = self._set_track_name(track_index, name)
                        elif command_type == "create_clip":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            length = params.get("length", 4.0)
                            result = self._create_clip(track_index, clip_index, length)
                        elif command_type == "add_notes_to_clip":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            notes = params.get("notes", [])
                            result = self._add_notes_to_clip(track_index, clip_index, notes)
                        elif command_type == "set_clip_name":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            name = params.get("name", "")
                            result = self._set_clip_name(track_index, clip_index, name)
                        elif command_type == "set_tempo":
                            tempo = params.get("tempo", 120.0)
                            result = self._set_tempo(tempo)
                        elif command_type == "fire_clip":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            result = self._fire_clip(track_index, clip_index)
                        elif command_type == "stop_clip":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            result = self._stop_clip(track_index, clip_index)
                        elif command_type == "start_playback":
                            result = self._start_playback()
                        elif command_type == "stop_playback":
                            result = self._stop_playback()
                        elif command_type == "load_instrument_or_effect":
                            track_index = params.get("track_index", 0)
                            uri = params.get("uri", "")
                            result = self._load_instrument_or_effect(track_index, uri)
                        elif command_type == "load_browser_item":
                            track_index = params.get("track_index", 0)
                            item_uri = params.get("item_uri", "")
                            result = self._load_browser_item(track_index, item_uri)
                        elif command_type == "load_master_item":
                            item_uri = params.get("item_uri", "")
                            result = self._load_browser_item_on_master(item_uri)
                        elif command_type == "load_return_item":
                            return_index = params.get("return_index", 0)
                            item_uri = params.get("item_uri", "")
                            result = self._load_browser_item_on_return(return_index, item_uri)
                        elif command_type == "create_return_track":
                            result = self._create_return_track()
                        elif command_type == "audio_to_midi_clip":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            conversion_type = params.get("conversion_type", "melody")
                            result = self._audio_to_midi_clip(track_index, clip_index, conversion_type)
                        elif command_type == "create_drum_rack_from_audio_clip":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            result = self._create_drum_rack_from_audio_clip(track_index, clip_index)
                        elif command_type == "create_midi_track_from_audio_clip":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            result = self._create_midi_track_from_audio_clip(track_index, clip_index)
                        elif command_type == "move_track_devices_to_drum_pad":
                            track_index = params.get("track_index", 0)
                            result = self._move_track_devices_to_drum_pad(track_index)
                        elif command_type == "convert_sliced_simpler_to_drum_rack":
                            track_index = params.get("track_index", 0)
                            device_index = params.get("device_index", 0)
                            result = self._convert_sliced_simpler_to_drum_rack(track_index, device_index)
                        elif command_type == "set_device_parameter":
                            track_index = params.get("track_index", 0)
                            device_index = params.get("device_index", 0)
                            parameter = params.get("parameter")
                            value = params.get("value", 0.0)
                            result = self._set_device_parameter(track_index, device_index, parameter, value)
                        elif command_type == "set_mixer_value":
                            track_index = params.get("track_index", 0)
                            param = params.get("param", "")
                            value = params.get("value", 0.0)
                            result = self._set_mixer_value(track_index, param, value)
                        elif command_type == "set_arrangement_loop":
                            start_beats = params.get("start_beats", 0.0)
                            length_beats = params.get("length_beats", 0.0)
                            result = self._set_arrangement_loop(start_beats, length_beats)
                        elif command_type == "clear_clip_envelope":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            device_index = params.get("device_index", -1)
                            parameter = params.get("parameter")
                            result = self._clear_clip_envelope(track_index, clip_index, device_index, parameter)
                        # --- Tier 1 writes ---
                        elif command_type == "duplicate_track":
                            track_index = params.get("track_index", 0)
                            result = self._duplicate_track(track_index)
                        elif command_type == "delete_track":
                            track_index = params.get("track_index", 0)
                            result = self._delete_track(track_index)
                        elif command_type == "undo":
                            result = self._undo()
                        elif command_type == "redo":
                            result = self._redo()
                        elif command_type == "capture_midi":
                            result = self._capture_midi()
                        elif command_type == "stop_all_clips":
                            result = self._stop_all_clips()
                        elif command_type == "create_audio_track":
                            index = params.get("index", -1)
                            result = self._create_audio_track(index)
                        # --- Tier 2 writes ---
                        elif command_type == "delete_device":
                            track_index = params.get("track_index", 0)
                            device_index = params.get("device_index", 0)
                            result = self._delete_device(track_index, device_index)
                        elif command_type == "move_device":
                            track_index = params.get("track_index", 0)
                            from_index = params.get("from_index", 0)
                            to_index = params.get("to_index", 0)
                            result = self._move_device(track_index, from_index, to_index)
                        elif command_type == "set_return_mixer_value":
                            return_index = params.get("return_index", 0)
                            param = params.get("param", "")
                            value = params.get("value", 0.0)
                            result = self._set_return_mixer_value(return_index, param, value)
                        elif command_type == "set_track_routing":
                            track_index = params.get("track_index", 0)
                            direction = params.get("direction", "")
                            kind = params.get("kind", "")
                            display_name = params.get("display_name", "")
                            result = self._set_track_routing(track_index, direction, kind, display_name)
                        elif command_type == "set_track_state":
                            track_index = params.get("track_index", 0)
                            attribute = params.get("attribute", "")
                            value = params.get("value", False)
                            result = self._set_track_state(track_index, attribute, value)
                        # --- Tier 3 writes ---
                        elif command_type == "delete_arrangement_clip":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            result = self._delete_arrangement_clip(track_index, clip_index)
                        elif command_type == "set_clip_loop_region":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            loop_start = params.get("loop_start", 0.0)
                            loop_end = params.get("loop_end", 0.0)
                            result = self._set_clip_loop_region(track_index, clip_index, loop_start, loop_end)
                        elif command_type == "jump_to_beat":
                            beat = params.get("beat", 0.0)
                            result = self._jump_to_beat(beat)
                        # --- Clip envelope writes ---
                        elif command_type == "set_clip_envelope_point":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            param_path = params.get("param_path", "")
                            time = params.get("time", 0.0)
                            value = params.get("value", 0.0)
                            length = params.get("length", 0.0)
                            location = params.get("location", "session")
                            result = self._set_clip_envelope_point(
                                track_index, clip_index, param_path, time, value, length, location)
                        elif command_type == "set_clip_envelope_curve":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            param_path = params.get("param_path", "")
                            points = params.get("points", [])
                            replace = params.get("replace", True)
                            location = params.get("location", "session")
                            result = self._set_clip_envelope_curve(
                                track_index, clip_index, param_path, points, replace, location)
                        elif command_type == "re_enable_automation":
                            track_index = params.get("track_index")
                            device_index = params.get("device_index")
                            parameter = params.get("parameter")
                            result = self._re_enable_automation(
                                track_index, device_index, parameter)
                        # --- Rack chain / drum pad writes ---
                        elif command_type == "set_chain_state":
                            track_index = params.get("track_index", 0)
                            device_index = params.get("device_index", 0)
                            chain_index = params.get("chain_index", 0)
                            attribute = params.get("attribute", "mute")
                            value = params.get("value", False)
                            result = self._set_chain_state(
                                track_index, device_index, chain_index, attribute, value)
                        elif command_type == "set_chain_mixer_value":
                            track_index = params.get("track_index", 0)
                            device_index = params.get("device_index", 0)
                            chain_index = params.get("chain_index", 0)
                            param = params.get("param", "volume")
                            value = params.get("value", 0.0)
                            result = self._set_chain_mixer_value(
                                track_index, device_index, chain_index, param, value)
                        elif command_type == "set_drum_pad_state":
                            track_index = params.get("track_index", 0)
                            device_index = params.get("device_index", 0)
                            pad_note = params.get("pad_note", 36)
                            attribute = params.get("attribute", "mute")
                            value = params.get("value", False)
                            result = self._set_drum_pad_state(
                                track_index, device_index, pad_note, attribute, value)
                        # --- Master / return device parameter writes ---
                        elif command_type == "set_master_device_parameter":
                            device_index = params.get("device_index", 0)
                            parameter = params.get("parameter")
                            value = params.get("value", 0.0)
                            result = self._set_master_device_parameter(
                                device_index, parameter, value)
                        elif command_type == "set_return_device_parameter":
                            return_index = params.get("return_index", 0)
                            device_index = params.get("device_index", 0)
                            parameter = params.get("parameter")
                            value = params.get("value", 0.0)
                            result = self._set_return_device_parameter(
                                return_index, device_index, parameter, value)
                        # --- High-value 6 writes (2026-05-17) ---
                        elif command_type == "set_song_scale":
                            scale_name = params.get("scale_name")
                            root_note = params.get("root_note")
                            in_key = params.get("in_key")
                            result = self._set_song_scale(scale_name, root_note, in_key)
                        elif command_type == "quantize_clip_notes":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            grid = params.get("grid", "1/16")
                            amount = params.get("amount", 1.0)
                            quantize_pitch = params.get("quantize_pitch", False)
                            result = self._quantize_clip_notes(
                                track_index, clip_index, grid, amount, quantize_pitch)
                        elif command_type == "set_or_delete_cue":
                            time = params.get("time")
                            name = params.get("name")
                            result = self._set_or_delete_cue(time, name)
                        elif command_type == "jump_to_cue":
                            direction = params.get("direction", "next")
                            result = self._jump_to_cue(direction)
                        elif command_type == "delete_cue_by_index":
                            cue_index = params.get("cue_index", 0)
                            result = self._delete_cue_by_index(cue_index)
                        elif command_type == "set_groove_params":
                            groove_index = params.get("groove_index", 0)
                            fields = {
                                k: params.get(k) for k in
                                ("amount", "timing", "quantization_amount",
                                 "random", "velocity_amount", "base")
                                if k in params
                            }
                            result = self._set_groove_params(groove_index, **fields)
                        elif command_type == "assign_groove_to_clip":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            groove_index = params.get("groove_index", -1)
                            result = self._assign_groove_to_clip(
                                track_index, clip_index, groove_index)
                        elif command_type == "set_clip_warping":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            warping = params.get("warping", True)
                            result = self._set_clip_warping(track_index, clip_index, warping)
                        elif command_type == "set_warp_mode":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            mode = params.get("mode", "Beats")
                            result = self._set_warp_mode(track_index, clip_index, mode)
                        elif command_type == "set_selection":
                            kind = params.get("kind", "track")
                            index = params.get("index")
                            scene_index = params.get("scene_index")
                            return_index = params.get("return_index")
                            clip_index = params.get("clip_index")
                            result = self._set_selection(
                                kind, index, scene_index, return_index, clip_index)
                        # --- Transport batch (2026-05-17) ---
                        elif command_type == "set_metronome":
                            result = self._set_metronome(params.get("enabled", False))
                        elif command_type == "set_count_in":
                            result = self._set_count_in(params.get("bars", 0))
                        elif command_type == "set_record_quantization":
                            result = self._set_record_quantization(
                                midi_quant=params.get("midi_quant"),
                                trigger_quant=params.get("trigger_quant"),
                                swing=params.get("swing"),
                            )
                        elif command_type == "set_time_signature":
                            result = self._set_time_signature(
                                params.get("numerator", 4),
                                params.get("denominator", 4))
                        elif command_type == "set_session_record":
                            result = self._set_session_record(
                                session_record=params.get("session_record"),
                                arrangement_overdub=params.get("arrangement_overdub"),
                                back_to_arranger=params.get("back_to_arranger"),
                            )
                        elif command_type == "set_punch_region":
                            result = self._set_punch_region(
                                punch_in=params.get("punch_in"),
                                punch_out=params.get("punch_out"),
                            )
                        elif command_type == "tap_tempo":
                            result = self._tap_tempo()
                        elif command_type == "bump_tempo":
                            result = self._bump_tempo(params.get("delta_bpm", 0.1))
                        # --- Scenes batch (2026-05-17) ---
                        elif command_type == "create_scene":
                            result = self._create_scene(params.get("index", -1))
                        elif command_type == "delete_scene":
                            result = self._delete_scene(params.get("scene_index", 0))
                        elif command_type == "duplicate_scene":
                            result = self._duplicate_scene(params.get("scene_index", 0))
                        elif command_type == "capture_and_insert_scene":
                            result = self._capture_and_insert_scene()
                        elif command_type == "set_scene_props":
                            result = self._set_scene_props(
                                scene_index=params.get("scene_index", 0),
                                name=params.get("name"),
                                color=params.get("color"),
                                color_index=params.get("color_index"),
                                tempo=params.get("tempo"),
                                signature_numerator=params.get("signature_numerator"),
                                signature_denominator=params.get("signature_denominator"),
                            )
                        elif command_type == "fire_scene":
                            result = self._fire_scene(params.get("scene_index", 0))
                        # --- Track-state extras (2026-05-17) ---
                        elif command_type == "set_track_monitoring":
                            result = self._set_track_monitoring(
                                params.get("track_index", 0),
                                params.get("mode", "auto"))
                        elif command_type == "set_track_freeze":
                            result = self._set_track_freeze(
                                params.get("track_index", 0),
                                params.get("freeze", True))
                        elif command_type == "set_track_color":
                            result = self._set_track_color(
                                params.get("track_index", 0),
                                color=params.get("color"),
                                color_index=params.get("color_index"))
                        elif command_type == "set_track_fold":
                            result = self._set_track_fold(
                                params.get("track_index", 0),
                                params.get("fold_state", False))
                        # --- Clip details (2026-05-17) ---
                        elif command_type == "set_clip_color":
                            result = self._set_clip_color(
                                params.get("track_index", 0),
                                params.get("clip_index", 0),
                                color=params.get("color"),
                                color_index=params.get("color_index"))
                        elif command_type == "set_clip_gain":
                            result = self._set_clip_gain(
                                params.get("track_index", 0),
                                params.get("clip_index", 0),
                                params.get("gain", 0.5))
                        elif command_type == "set_clip_pitch":
                            result = self._set_clip_pitch(
                                params.get("track_index", 0),
                                params.get("clip_index", 0),
                                coarse=params.get("coarse"),
                                fine=params.get("fine"))
                        elif command_type == "set_clip_launch_settings":
                            result = self._set_clip_launch_settings(
                                params.get("track_index", 0),
                                params.get("clip_index", 0),
                                launch_mode=params.get("launch_mode"),
                                launch_quantization=params.get("launch_quantization"),
                                legato=params.get("legato"),
                                looping=params.get("looping"))
                        elif command_type == "set_clip_follow_action":
                            result = self._set_clip_follow_action(
                                params.get("track_index", 0),
                                params.get("clip_index", 0),
                                enabled=params.get("enabled"),
                                action_a=params.get("action_a"),
                                action_b=params.get("action_b"),
                                chance_a=params.get("chance_a"),
                                chance_b=params.get("chance_b"),
                                time_beats=params.get("time_beats"))
                        # --- Warp markers (2026-05-17) ---
                        elif command_type == "add_warp_marker":
                            result = self._add_warp_marker(
                                params.get("track_index", 0),
                                params.get("clip_index", 0),
                                params.get("beat_time", 0.0),
                                params.get("sample_time", 0.0))
                        elif command_type == "remove_warp_marker":
                            result = self._remove_warp_marker(
                                params.get("track_index", 0),
                                params.get("clip_index", 0),
                                params.get("beat_time", 0.0))
                        elif command_type == "move_warp_marker":
                            result = self._move_warp_marker(
                                params.get("track_index", 0),
                                params.get("clip_index", 0),
                                params.get("beat_time", 0.0),
                                params.get("new_beat_time", 0.0))

                        # Put the result in the queue
                        response_queue.put({"status": "success", "result": result})
                    except Exception as e:
                        self.log_message("Error in main thread task: " + str(e))
                        self.log_message(traceback.format_exc())
                        response_queue.put({"status": "error", "message": str(e)})
                
                # Schedule the task to run on the main thread
                try:
                    self.schedule_message(0, main_thread_task)
                except AssertionError:
                    # If we're already on the main thread, execute directly
                    main_thread_task()
                
                # Wait for the response with a timeout
                try:
                    task_response = response_queue.get(timeout=10.0)
                    if task_response.get("status") == "error":
                        response["status"] = "error"
                        response["message"] = task_response.get("message", "Unknown error")
                    else:
                        response["result"] = task_response.get("result", {})
                except queue.Empty:
                    response["status"] = "error"
                    response["message"] = "Timeout waiting for operation to complete"
            elif command_type == "get_browser_item":
                uri = params.get("uri", None)
                path = params.get("path", None)
                response["result"] = self._get_browser_item(uri, path)
            elif command_type == "get_browser_categories":
                category_type = params.get("category_type", "all")
                response["result"] = self._get_browser_categories(category_type)
            elif command_type == "get_browser_items":
                path = params.get("path", "")
                item_type = params.get("item_type", "all")
                response["result"] = self._get_browser_items(path, item_type)
            # Add the new browser commands
            elif command_type == "get_browser_tree":
                category_type = params.get("category_type", "all")
                response["result"] = self.get_browser_tree(category_type)
            elif command_type == "get_browser_items_at_path":
                path = params.get("path", "")
                response["result"] = self.get_browser_items_at_path(path)
            else:
                response["status"] = "error"
                response["message"] = "Unknown command: " + command_type
        except Exception as e:
            self.log_message("Error processing command: " + str(e))
            self.log_message(traceback.format_exc())
            response["status"] = "error"
            response["message"] = str(e)
        
        return response
    
    # Command implementations
    
    def _get_session_info(self):
        """Get information about the current session"""
        try:
            result = {
                "tempo": self._song.tempo,
                "signature_numerator": self._song.signature_numerator,
                "signature_denominator": self._song.signature_denominator,
                "track_count": len(self._song.tracks),
                "return_track_count": len(self._song.return_tracks),
                "master_track": {
                    "name": "Master",
                    "volume": self._song.master_track.mixer_device.volume.value,
                    "panning": self._song.master_track.mixer_device.panning.value
                }
            }
            return result
        except Exception as e:
            self.log_message("Error getting session info: " + str(e))
            raise
    
    def _get_track_info(self, track_index):
        """Get information about a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            # Get clip slots
            clip_slots = []
            for slot_index, slot in enumerate(track.clip_slots):
                clip_info = None
                if slot.has_clip:
                    clip = slot.clip
                    clip_info = {
                        "name": clip.name,
                        "length": clip.length,
                        "is_playing": clip.is_playing,
                        "is_recording": clip.is_recording
                    }
                
                clip_slots.append({
                    "index": slot_index,
                    "has_clip": slot.has_clip,
                    "clip": clip_info
                })
            
            # Get devices
            devices = []
            for device_index, device in enumerate(track.devices):
                devices.append({
                    "index": device_index,
                    "name": device.name,
                    "class_name": device.class_name,
                    "type": self._get_device_type(device)
                })
            
            result = {
                "index": track_index,
                "name": track.name,
                "is_audio_track": track.has_audio_input,
                "is_midi_track": track.has_midi_input,
                "mute": track.mute,
                "solo": track.solo,
                "arm": track.arm if getattr(track, "can_be_armed", False) else False,
                "volume": track.mixer_device.volume.value,
                "panning": track.mixer_device.panning.value,
                "clip_slots": clip_slots,
                "devices": devices
            }
            return result
        except Exception as e:
            self.log_message("Error getting track info: " + str(e))
            raise
    
    def _create_midi_track(self, index):
        """Create a new MIDI track at the specified index"""
        try:
            # Create the track
            self._song.create_midi_track(index)
            
            # Get the new track
            new_track_index = len(self._song.tracks) - 1 if index == -1 else index
            new_track = self._song.tracks[new_track_index]
            
            result = {
                "index": new_track_index,
                "name": new_track.name
            }
            return result
        except Exception as e:
            self.log_message("Error creating MIDI track: " + str(e))
            raise
    
    
    def _set_track_name(self, track_index, name):
        """Set the name of a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            # Set the name
            track = self._song.tracks[track_index]
            track.name = name
            
            result = {
                "name": track.name
            }
            return result
        except Exception as e:
            self.log_message("Error setting track name: " + str(e))
            raise
    
    def _create_clip(self, track_index, clip_index, length):
        """Create a new MIDI clip in the specified track and clip slot"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            # Check if the clip slot already has a clip
            if clip_slot.has_clip:
                raise Exception("Clip slot already has a clip")
            
            # Create the clip
            clip_slot.create_clip(length)
            
            result = {
                "name": clip_slot.clip.name,
                "length": clip_slot.clip.length
            }
            return result
        except Exception as e:
            self.log_message("Error creating clip: " + str(e))
            raise
    
    def _add_notes_to_clip(self, track_index, clip_index, notes):
        """REPLACE the MIDI notes in a clip with the given list.

        Despite the name, this is a replace operation. Live 12 keeps notes in
        separate stores (old `set_notes`/`get_notes` vs new `add_new_notes`/
        `remove_notes_extended`); a previous attempt to clear via
        `remove_notes_extended(0, 0, length, 128)` followed by `set_notes(...)`
        did NOT remove notes added through the UI on Live 12.3.7 — original
        notes survived alongside the new ones.

        The reliable pattern (used by Push and most LOM tools) is the OLD-API
        select-all + replace-selected combination, which operates on the
        UI-visible note set regardless of underlying storage.

        Falls back to remove_notes_extended + add_new_notes if the old-API
        methods are unavailable (very old Live versions).
        """
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")

            clip_slot = track.clip_slots[clip_index]

            if not clip_slot.has_clip:
                raise Exception("No clip in slot")

            clip = clip_slot.clip

            # Build the (pitch, start_time, duration, velocity, mute) tuple Live expects
            live_notes_tuple = tuple(
                (
                    int(note.get("pitch", 60)),
                    float(note.get("start_time", 0.0)),
                    float(note.get("duration", 0.25)),
                    int(note.get("velocity", 100)),
                    bool(note.get("mute", False)),
                )
                for note in notes
            )

            # Canonical "replace all notes" — select all UI-visible notes then
            # replace with the new tuple. Works for both old- and new-API
            # storage because the selection is at the UI layer.
            try:
                clip.select_all_notes()
                clip.replace_selected_notes(live_notes_tuple)
                try:
                    clip.deselect_all_notes()
                except AttributeError:
                    pass  # not all Live versions expose this cleanup method
            except AttributeError:
                # Pre-Live-11 fallback: new-API clear + add
                try:
                    clip.remove_notes_extended(0, 0, clip.length, 128)
                except AttributeError:
                    pass
                clip.set_notes(live_notes_tuple)

            result = {
                "note_count": len(notes)
            }
            return result
        except Exception as e:
            self.log_message("Error adding notes to clip: " + str(e))
            raise
    
    def _set_clip_name(self, track_index, clip_index, name):
        """Set the name of a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            
            clip = clip_slot.clip
            clip.name = name
            
            result = {
                "name": clip.name
            }
            return result
        except Exception as e:
            self.log_message("Error setting clip name: " + str(e))
            raise
    
    def _set_tempo(self, tempo):
        """Set the tempo of the session"""
        try:
            self._song.tempo = tempo

            result = {
                "tempo": self._song.tempo
            }
            return result
        except Exception as e:
            self.log_message("Error setting tempo: " + str(e))
            raise

    def _resolve_parameter(self, device, key):
        """Resolve a parameter key (int index or str name) to a LOM parameter object."""
        params = device.parameters
        if isinstance(key, bool):
            raise ValueError("Parameter key must be int or string, got bool")
        if isinstance(key, int):
            if key < 0 or key >= len(params):
                raise IndexError("Parameter index {0} out of range (0..{1})".format(
                    key, len(params) - 1))
            return params[key], key
        if isinstance(key, str):
            for i, p in enumerate(params):
                if p.name == key:
                    return p, i
            # Second pass: case-insensitive match to help with casing drift
            lk = key.lower()
            for i, p in enumerate(params):
                if p.name.lower() == lk:
                    return p, i
            names = [p.name for p in params]
            raise ValueError("Parameter '{0}' not found. Available: {1}".format(
                key, names))
        raise ValueError("Parameter key must be int index or string name")

    def _get_device(self, track_index, device_index):
        """Bounds-check and return (track, device)."""
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        if device_index < 0 or device_index >= len(track.devices):
            raise IndexError("Device index out of range")
        return track, track.devices[device_index]

    def _param_info(self, param, index):
        return {
            "index": index,
            "name": param.name,
            "value": param.value,
            "min": param.min,
            "max": param.max,
            "is_enabled": param.is_enabled,
        }

    def _get_device_parameters(self, track_index, device_index):
        """List all parameters on a device."""
        try:
            _, device = self._get_device(track_index, device_index)
            return {
                "track_index": track_index,
                "device_index": device_index,
                "device_name": device.name,
                "parameters": [
                    self._param_info(p, i) for i, p in enumerate(device.parameters)
                ],
            }
        except Exception as e:
            self.log_message("Error getting device parameters: " + str(e))
            raise

    def _get_device_parameter_value(self, track_index, device_index, parameter):
        """Read a single device parameter."""
        try:
            _, device = self._get_device(track_index, device_index)
            param, index = self._resolve_parameter(device, parameter)
            return self._param_info(param, index)
        except Exception as e:
            self.log_message("Error getting device parameter value: " + str(e))
            raise

    def _set_device_parameter(self, track_index, device_index, parameter, value):
        """Set a device parameter, clamped to [min, max]."""
        try:
            _, device = self._get_device(track_index, device_index)
            param, index = self._resolve_parameter(device, parameter)
            if not param.is_enabled:
                raise Exception("Parameter '{0}' is not enabled".format(param.name))
            clamped = max(param.min, min(param.max, float(value)))
            param.value = clamped
            return {
                "track_index": track_index,
                "device_index": device_index,
                "parameter_index": index,
                "name": param.name,
                "value": param.value,
                "clamped": clamped != float(value),
            }
        except Exception as e:
            self.log_message("Error setting device parameter: " + str(e))
            raise

    # ---------------- Master / return device parameter helpers ----------------

    def _get_master_device(self, device_index):
        master = self._song.master_track
        if device_index < 0 or device_index >= len(master.devices):
            raise IndexError("Master device index {0} out of range (0..{1})".format(
                device_index, len(master.devices) - 1))
        return master.devices[device_index]

    def _get_return_device(self, return_index, device_index):
        if return_index < 0 or return_index >= len(self._song.return_tracks):
            raise IndexError("Return index {0} out of range (0..{1})".format(
                return_index, len(self._song.return_tracks) - 1))
        rt = self._song.return_tracks[return_index]
        if device_index < 0 or device_index >= len(rt.devices):
            raise IndexError("Return device index {0} out of range (0..{1})".format(
                device_index, len(rt.devices) - 1))
        return rt.devices[device_index]

    def _get_master_device_parameters(self, device_index):
        try:
            device = self._get_master_device(device_index)
            return {
                "track": "master",
                "device_index": device_index,
                "device_name": device.name,
                "parameters": [
                    self._param_info(p, i) for i, p in enumerate(device.parameters)
                ],
            }
        except Exception as e:
            self.log_message("Error getting master device parameters: " + str(e))
            raise

    def _set_master_device_parameter(self, device_index, parameter, value):
        try:
            device = self._get_master_device(device_index)
            param, index = self._resolve_parameter(device, parameter)
            if not param.is_enabled:
                raise Exception("Parameter '{0}' is not enabled".format(param.name))
            clamped = max(param.min, min(param.max, float(value)))
            param.value = clamped
            return {
                "track": "master",
                "device_index": device_index,
                "parameter_index": index,
                "name": param.name,
                "value": param.value,
                "clamped": clamped != float(value),
            }
        except Exception as e:
            self.log_message("Error setting master device parameter: " + str(e))
            raise

    def _get_return_device_parameters(self, return_index, device_index):
        try:
            device = self._get_return_device(return_index, device_index)
            return {
                "return_index": return_index,
                "device_index": device_index,
                "device_name": device.name,
                "parameters": [
                    self._param_info(p, i) for i, p in enumerate(device.parameters)
                ],
            }
        except Exception as e:
            self.log_message("Error getting return device parameters: " + str(e))
            raise

    def _set_return_device_parameter(self, return_index, device_index, parameter, value):
        try:
            device = self._get_return_device(return_index, device_index)
            param, index = self._resolve_parameter(device, parameter)
            if not param.is_enabled:
                raise Exception("Parameter '{0}' is not enabled".format(param.name))
            clamped = max(param.min, min(param.max, float(value)))
            param.value = clamped
            return {
                "return_index": return_index,
                "device_index": device_index,
                "parameter_index": index,
                "name": param.name,
                "value": param.value,
                "clamped": clamped != float(value),
            }
        except Exception as e:
            self.log_message("Error setting return device parameter: " + str(e))
            raise

    def _set_mixer_value(self, track_index, param, value):
        """Set mixer volume/panning/send on a track."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            mixer = track.mixer_device

            key = param.lower() if isinstance(param, str) else param
            if key == "volume":
                target = mixer.volume
            elif key in ("panning", "pan"):
                target = mixer.panning
            elif isinstance(key, str) and key.startswith("send:"):
                try:
                    send_idx = int(key.split(":", 1)[1])
                except (ValueError, IndexError):
                    raise ValueError("Bad send spec '{0}'; expected 'send:N'".format(param))
                if send_idx < 0 or send_idx >= len(mixer.sends):
                    raise IndexError("Send index {0} out of range (0..{1})".format(
                        send_idx, len(mixer.sends) - 1))
                target = mixer.sends[send_idx]
            else:
                raise ValueError("Unknown mixer param '{0}'. Use 'volume', 'panning', or 'send:N'".format(param))

            clamped = max(target.min, min(target.max, float(value)))
            target.value = clamped
            return {
                "track_index": track_index,
                "param": param,
                "value": target.value,
                "clamped": clamped != float(value),
            }
        except Exception as e:
            self.log_message("Error setting mixer value: " + str(e))
            raise

    def _set_arrangement_loop(self, start_beats, length_beats):
        """Set the arrangement loop region."""
        try:
            start = float(start_beats)
            length = float(length_beats)
            if start < 0:
                raise ValueError("start_beats must be >= 0")
            if length <= 0:
                raise ValueError("length_beats must be > 0")
            # Order matters: some LOM versions reject length that would push past
            # song end. Set start first, then length.
            self._song.loop_start = start
            self._song.loop_length = length
            return {
                "loop_start": self._song.loop_start,
                "loop_length": self._song.loop_length,
            }
        except Exception as e:
            self.log_message("Error setting arrangement loop: " + str(e))
            raise

    def _clear_clip_envelope(self, track_index, clip_index, device_index, parameter):
        """Clear automation envelope(s) on a session-view clip."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            slot = track.clip_slots[clip_index]
            if not slot.has_clip:
                raise Exception("No clip in slot")
            clip = slot.clip

            if parameter is None:
                clip.clear_all_envelopes()
                return {
                    "track_index": track_index,
                    "clip_index": clip_index,
                    "cleared": "all",
                }

            if device_index is None or device_index < 0:
                raise ValueError("device_index is required when clearing a specific parameter")
            if device_index >= len(track.devices):
                raise IndexError("Device index out of range")
            device = track.devices[device_index]
            param, _ = self._resolve_parameter(device, parameter)
            clip.clear_envelope(param)
            return {
                "track_index": track_index,
                "clip_index": clip_index,
                "device_index": device_index,
                "parameter": param.name,
                "cleared": "single",
            }
        except Exception as e:
            self.log_message("Error clearing clip envelope: " + str(e))
            raise

    # ---------------- Tier 1 helpers ----------------

    def _get_clip_notes(self, track_index, clip_index):
        """Read MIDI notes from a session-view clip."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            slot = track.clip_slots[clip_index]
            if not slot.has_clip:
                raise Exception("No clip in slot")
            clip = slot.clip
            if not clip.is_midi_clip:
                raise Exception("Clip is not a MIDI clip")
            # get_notes(from_time, from_pitch, time_span, pitch_span) — old API
            # returns tuples of (pitch, start_time, duration, velocity, mute)
            length = max(clip.length, 1.0)
            notes_raw = clip.get_notes(0, 0, length, 128)
            notes = []
            for n in notes_raw:
                notes.append({
                    "pitch": int(n[0]),
                    "start_time": float(n[1]),
                    "duration": float(n[2]),
                    "velocity": int(n[3]),
                    "mute": bool(n[4]),
                })
            return {
                "track_index": track_index,
                "clip_index": clip_index,
                "clip_name": clip.name,
                "length": clip.length,
                "note_count": len(notes),
                "notes": notes,
            }
        except Exception as e:
            self.log_message("Error getting clip notes: " + str(e))
            raise

    def _duplicate_track(self, track_index):
        """Duplicate a track via song.duplicate_track(index)."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            before_count = len(self._song.tracks)
            self._song.duplicate_track(track_index)
            after_count = len(self._song.tracks)
            new_index = track_index + 1 if after_count > before_count else -1
            name = self._song.tracks[new_index].name if new_index >= 0 else ""
            return {
                "source_index": track_index,
                "new_index": new_index,
                "name": name,
                "track_count": after_count,
            }
        except Exception as e:
            self.log_message("Error duplicating track: " + str(e))
            raise

    def _delete_track(self, track_index):
        """Delete a track by index."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            name = self._song.tracks[track_index].name
            self._song.delete_track(track_index)
            return {
                "deleted_index": track_index,
                "name": name,
                "track_count": len(self._song.tracks),
            }
        except Exception as e:
            self.log_message("Error deleting track: " + str(e))
            raise

    def _undo(self):
        """Undo the last action."""
        try:
            if not self._song.can_undo:
                return {"undone": False, "action": None}
            # song.undo() may return an action name string
            action = self._song.undo()
            return {
                "undone": True,
                "action": str(action) if action is not None else "",
            }
        except Exception as e:
            self.log_message("Error during undo: " + str(e))
            raise

    def _redo(self):
        """Redo the last undone action."""
        try:
            if not self._song.can_redo:
                return {"redone": False, "action": None}
            action = self._song.redo()
            return {
                "redone": True,
                "action": str(action) if action is not None else "",
            }
        except Exception as e:
            self.log_message("Error during redo: " + str(e))
            raise

    def _capture_midi(self):
        """Capture recently-played MIDI into a clip."""
        try:
            if not getattr(self._song, "can_capture_midi", False):
                raise Exception("Nothing to capture — arm a MIDI track and play something first")
            self._song.capture_midi()
            return {"status": "captured"}
        except RuntimeError as e:
            self.log_message("RuntimeError during capture_midi: " + str(e))
            raise Exception("capture_midi failed: " + str(e))
        except Exception as e:
            self.log_message("Error capturing MIDI: " + str(e))
            raise

    def _stop_all_clips(self):
        """Stop all session-view clips."""
        try:
            self._song.stop_all_clips()
            return {"stopped": True}
        except Exception as e:
            self.log_message("Error stopping all clips: " + str(e))
            raise

    def _create_audio_track(self, index):
        """Create a new audio track; mirror create_midi_track's signature."""
        try:
            try:
                self._song.create_audio_track(index)
            except TypeError:
                # Some LOM versions don't accept index
                self._song.create_audio_track()
            new_index = len(self._song.tracks) - 1 if index == -1 else index
            if new_index < 0 or new_index >= len(self._song.tracks):
                new_index = len(self._song.tracks) - 1
            return {
                "index": new_index,
                "name": self._song.tracks[new_index].name,
            }
        except Exception as e:
            self.log_message("Error creating audio track: " + str(e))
            raise

    # ---------------- Tier 2 helpers ----------------

    def _delete_device(self, track_index, device_index):
        """Delete a top-level device from a track."""
        try:
            track, device = self._get_device(track_index, device_index)
            name = device.name
            track.delete_device(device_index)
            return {
                "track_index": track_index,
                "device_index": device_index,
                "name": name,
                "device_count": len(track.devices),
            }
        except Exception as e:
            self.log_message("Error deleting device: " + str(e))
            raise

    def _move_device(self, track_index, from_index, to_index):
        """Reorder a device within its track via song.move_device.

        Caller passes the desired FINAL position in the resulting list.
        LOM's move_device uses 'insert-before' semantics on the pre-move list,
        so forward moves need an extra +1 (per Push2/device_navigation.py
        _move_right at line 247 which uses device_index + 2 to move one slot right).
        """
        try:
            track, device = self._get_device(track_index, from_index)
            device_count = len(track.devices)
            if to_index < 0 or to_index >= device_count:
                raise IndexError("to_index out of range (0..{0})".format(device_count - 1))
            # lom_target for a forward move can equal device_count (append at end), which is valid.
            if to_index == from_index:
                return {
                    "track_index": track_index,
                    "from_index": from_index,
                    "to_index": to_index,
                    "name": device.name,
                    "moved": False,
                }
            name = device.name
            # LOM insert-before operates on the ORIGINAL list (before removal).
            # Forward moves need +1: moving from F to final T means inserting
            # before original T+1 (so after removal of F the device lands at T).
            lom_target = to_index + 1 if to_index > from_index else to_index
            self._song.move_device(device, track, lom_target)
            return {
                "track_index": track_index,
                "from_index": from_index,
                "to_index": to_index,
                "name": name,
                "moved": True,
            }
        except Exception as e:
            self.log_message("Error moving device: " + str(e))
            raise

    def _return_track_devices(self, track):
        devices = []
        for i, d in enumerate(track.devices):
            devices.append({
                "index": i,
                "name": d.name,
                "class_name": d.class_name,
                "type": self._get_device_type(d),
            })
        return devices

    def _get_return_track_info(self, return_index):
        """Get a return track's state."""
        try:
            if return_index < 0 or return_index >= len(self._song.return_tracks):
                raise IndexError("Return track index out of range")
            track = self._song.return_tracks[return_index]
            sends = [s.value for s in track.mixer_device.sends]
            return {
                "index": return_index,
                "name": track.name,
                "mute": track.mute,
                "solo": track.solo,
                "volume": track.mixer_device.volume.value,
                "panning": track.mixer_device.panning.value,
                "sends": sends,
                "devices": self._return_track_devices(track),
            }
        except Exception as e:
            self.log_message("Error getting return track info: " + str(e))
            raise

    def _set_return_mixer_value(self, return_index, param, value):
        """Set mixer value on a return track."""
        try:
            if return_index < 0 or return_index >= len(self._song.return_tracks):
                raise IndexError("Return track index out of range")
            track = self._song.return_tracks[return_index]
            mixer = track.mixer_device
            key = param.lower() if isinstance(param, str) else param
            if key == "volume":
                target = mixer.volume
            elif key in ("panning", "pan"):
                target = mixer.panning
            elif isinstance(key, str) and key.startswith("send:"):
                try:
                    send_idx = int(key.split(":", 1)[1])
                except (ValueError, IndexError):
                    raise ValueError("Bad send spec '{0}'; expected 'send:N'".format(param))
                if send_idx < 0 or send_idx >= len(mixer.sends):
                    raise IndexError("Send index {0} out of range".format(send_idx))
                target = mixer.sends[send_idx]
            else:
                raise ValueError("Unknown mixer param '{0}'. Use 'volume', 'panning', or 'send:N'".format(param))
            clamped = max(target.min, min(target.max, float(value)))
            target.value = clamped
            return {
                "return_index": return_index,
                "param": param,
                "value": target.value,
                "clamped": clamped != float(value),
            }
        except Exception as e:
            self.log_message("Error setting return mixer value: " + str(e))
            raise

    def _routing_attrs(self, track, direction, kind):
        """Resolve (current_attr_name, available_attr_name) for routing access."""
        if direction not in ("input", "output"):
            raise ValueError("direction must be 'input' or 'output'")
        if kind not in ("type", "channel"):
            raise ValueError("kind must be 'type' or 'channel'")
        current = "{0}_routing_{1}".format(direction, kind)
        available = "available_{0}_routing_{1}s".format(direction, kind)
        return current, available

    def _get_track_routing(self, track_index):
        """Get all routing info for a track."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            result = {"track_index": track_index, "name": track.name}
            for direction in ("input", "output"):
                for kind in ("type", "channel"):
                    current_attr, available_attr = self._routing_attrs(track, direction, kind)
                    current = getattr(track, current_attr, None)
                    available = getattr(track, available_attr, None) or []
                    key_current = "{0}_{1}".format(direction, kind)
                    key_available = "available_{0}_{1}s".format(direction, kind)
                    result[key_current] = getattr(current, "display_name", None) if current else None
                    result[key_available] = [getattr(o, "display_name", str(o)) for o in available]
            return result
        except Exception as e:
            self.log_message("Error getting track routing: " + str(e))
            raise

    def _resolve_routing_option(self, track, direction, kind, display_name):
        """Find a routing option on track by display_name (case-insensitive fallback)."""
        _, available_attr = self._routing_attrs(track, direction, kind)
        options = getattr(track, available_attr, None) or []
        for o in options:
            if getattr(o, "display_name", None) == display_name:
                return o
        lk = display_name.lower()
        for o in options:
            dn = getattr(o, "display_name", "")
            if dn.lower() == lk:
                return o
        names = [getattr(o, "display_name", str(o)) for o in options]
        raise ValueError("Routing option '{0}' not found for {1} {2}. Available: {3}".format(
            display_name, direction, kind, names))

    def _set_track_routing(self, track_index, direction, kind, display_name):
        """Set one routing field on a track."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            option = self._resolve_routing_option(track, direction, kind, display_name)
            current_attr, _ = self._routing_attrs(track, direction, kind)
            setattr(track, current_attr, option)
            return {
                "track_index": track_index,
                "direction": direction,
                "kind": kind,
                "display_name": getattr(getattr(track, current_attr), "display_name", display_name),
            }
        except Exception as e:
            self.log_message("Error setting track routing: " + str(e))
            raise

    def _set_track_state(self, track_index, attribute, value):
        """Set mute/solo/arm on a track."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            attr = attribute.lower() if isinstance(attribute, str) else attribute
            if attr == "mute":
                track.mute = bool(value)
                return {"track_index": track_index, "attribute": "mute", "value": track.mute}
            elif attr == "solo":
                track.solo = bool(value)
                return {"track_index": track_index, "attribute": "solo", "value": track.solo}
            elif attr == "arm":
                if not getattr(track, "can_be_armed", False):
                    raise Exception("Track {0} ('{1}') cannot be armed".format(track_index, track.name))
                track.arm = bool(value)
                return {"track_index": track_index, "attribute": "arm", "value": track.arm}
            else:
                raise ValueError("attribute must be 'mute', 'solo', or 'arm'")
        except Exception as e:
            self.log_message("Error setting track state: " + str(e))
            raise

    # ---------------- Tier 3 helpers ----------------

    def _get_arrangement_clips(self, track_index):
        """List arrangement clips on a track."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            clips = getattr(track, "arrangement_clips", None)
            if clips is None:
                raise Exception("Track {0} has no arrangement_clips attribute".format(track_index))
            out = []
            for i, c in enumerate(clips):
                out.append({
                    "index": i,
                    "name": c.name,
                    "start_time": c.start_time,
                    "end_time": c.end_time,
                    "length": c.length,
                    "is_midi_clip": c.is_midi_clip,
                })
            return {
                "track_index": track_index,
                "name": track.name,
                "clip_count": len(out),
                "clips": out,
            }
        except Exception as e:
            self.log_message("Error getting arrangement clips: " + str(e))
            raise

    def _delete_arrangement_clip(self, track_index, clip_index):
        """Delete an arrangement clip by position in the arrangement_clips tuple."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            clips = getattr(track, "arrangement_clips", None) or ()
            if clip_index < 0 or clip_index >= len(clips):
                raise IndexError("Arrangement clip index out of range (0..{0})".format(len(clips) - 1))
            clip = clips[clip_index]
            info = {
                "track_index": track_index,
                "clip_index": clip_index,
                "name": clip.name,
                "start_time": clip.start_time,
            }
            track.delete_clip(clip)
            return info
        except Exception as e:
            self.log_message("Error deleting arrangement clip: " + str(e))
            raise

    def _set_clip_loop_region(self, track_index, clip_index, loop_start, loop_end):
        """Set loop brace inside a session-view clip."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            slot = track.clip_slots[clip_index]
            if not slot.has_clip:
                raise Exception("No clip in slot")
            clip = slot.clip
            start = float(loop_start)
            end = float(loop_end)
            if start < 0:
                raise ValueError("loop_start must be >= 0")
            if end <= start:
                raise ValueError("loop_end must be > loop_start")
            if end > clip.length:
                raise ValueError("loop_end ({0}) exceeds clip length ({1})".format(end, clip.length))
            # Collapse current region to [0, 0] first so neither new value collides
            # with the existing one (regardless of whether the new region is earlier
            # or later than the old one).
            clip.loop_start = 0.0
            clip.loop_end = end
            clip.loop_start = start
            return {
                "track_index": track_index,
                "clip_index": clip_index,
                "loop_start": clip.loop_start,
                "loop_end": clip.loop_end,
            }
        except Exception as e:
            self.log_message("Error setting clip loop region: " + str(e))
            raise

    def _jump_to_beat(self, beat):
        """Set current_song_time to an absolute beat position.

        Don't read current_song_time back — it's stale within the same main-thread
        tick (the setter is committed on the next tick but this handler runs
        synchronously inside schedule_message's callback).
        """
        try:
            b = float(beat)
            if b < 0:
                raise ValueError("beat must be >= 0")
            self._song.current_song_time = b
            return {"beat": b}
        except Exception as e:
            self.log_message("Error jumping to beat: " + str(e))
            raise

    def _fire_clip(self, track_index, clip_index):
        """Fire a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            
            clip_slot.fire()
            
            result = {
                "fired": True
            }
            return result
        except Exception as e:
            self.log_message("Error firing clip: " + str(e))
            raise
    
    def _stop_clip(self, track_index, clip_index):
        """Stop a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            clip_slot.stop()
            
            result = {
                "stopped": True
            }
            return result
        except Exception as e:
            self.log_message("Error stopping clip: " + str(e))
            raise
    
    
    def _start_playback(self):
        """Start playing the session"""
        try:
            self._song.start_playing()
            
            result = {
                "playing": self._song.is_playing
            }
            return result
        except Exception as e:
            self.log_message("Error starting playback: " + str(e))
            raise
    
    def _stop_playback(self):
        """Stop playing the session"""
        try:
            self._song.stop_playing()
            
            result = {
                "playing": self._song.is_playing
            }
            return result
        except Exception as e:
            self.log_message("Error stopping playback: " + str(e))
            raise
    
    def _get_browser_item(self, uri, path):
        """Get a browser item by URI or path"""
        try:
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")
                
            result = {
                "uri": uri,
                "path": path,
                "found": False
            }
            
            # Try to find by URI first if provided
            if uri:
                item = self._find_browser_item_by_uri(app.browser, uri)
                if item:
                    result["found"] = True
                    result["item"] = {
                        "name": item.name,
                        "is_folder": item.is_folder,
                        "is_device": item.is_device,
                        "is_loadable": item.is_loadable,
                        "uri": item.uri
                    }
                    return result
            
            # If URI not provided or not found, try by path
            if path:
                # Parse the path and navigate to the specified item
                path_parts = path.split("/")
                
                # Determine the root based on the first part
                current_item = None
                if path_parts[0].lower() == "nstruments":
                    current_item = app.browser.instruments
                elif path_parts[0].lower() == "sounds":
                    current_item = app.browser.sounds
                elif path_parts[0].lower() == "drums":
                    current_item = app.browser.drums
                elif path_parts[0].lower() == "audio_effects":
                    current_item = app.browser.audio_effects
                elif path_parts[0].lower() == "midi_effects":
                    current_item = app.browser.midi_effects
                else:
                    # Default to instruments if not specified
                    current_item = app.browser.instruments
                    # Don't skip the first part in this case
                    path_parts = ["instruments"] + path_parts
                
                # Navigate through the path
                for i in range(1, len(path_parts)):
                    part = path_parts[i]
                    if not part:  # Skip empty parts
                        continue
                    
                    found = False
                    for child in current_item.children:
                        if child.name.lower() == part.lower():
                            current_item = child
                            found = True
                            break
                    
                    if not found:
                        result["error"] = "Path part '{0}' not found".format(part)
                        return result
                
                # Found the item
                result["found"] = True
                result["item"] = {
                    "name": current_item.name,
                    "is_folder": current_item.is_folder,
                    "is_device": current_item.is_device,
                    "is_loadable": current_item.is_loadable,
                    "uri": current_item.uri
                }
            
            return result
        except Exception as e:
            self.log_message("Error getting browser item: " + str(e))
            self.log_message(traceback.format_exc())
            raise   
    
    
    
    def _load_browser_item(self, track_index, item_uri):
        """Load a browser item onto a track by its URI"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            
            # Find the browser item by URI
            item = self._find_browser_item_by_uri(app.browser, item_uri)
            
            if not item:
                raise ValueError("Browser item with URI '{0}' not found".format(item_uri))
            
            # Select the track
            self._song.view.selected_track = track
            
            # Load the item
            app.browser.load_item(item)
            
            result = {
                "loaded": True,
                "item_name": item.name,
                "track_name": track.name,
                "uri": item_uri
            }
            return result
        except Exception as e:
            self.log_message("Error loading browser item: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise

    def _load_browser_item_on_master(self, item_uri):
        """Load a browser item onto the master track via view.selected_track + browser.load_item.

        Validated 2026-05-17: closes the documented MCP gap that master devices
        could only be parameter-tuned. Now they can also be ADDED via MCP.
        """
        try:
            app = self.application()
            item = self._find_browser_item_by_uri(app.browser, item_uri)
            if not item:
                raise ValueError("Browser item with URI '{0}' not found".format(item_uri))
            master = self._song.master_track
            devices_before = [d.name for d in master.devices]
            self._song.view.selected_track = master
            app.browser.load_item(item)
            devices_after = [d.name for d in master.devices]
            # Diff respecting duplicates
            db_counter = {}
            for n in devices_before:
                db_counter[n] = db_counter.get(n, 0) + 1
            new_devices = []
            for n in devices_after:
                if db_counter.get(n, 0) > 0:
                    db_counter[n] -= 1
                else:
                    new_devices.append(n)
            return {
                "loaded": True,
                "item_name": item.name,
                "track_name": "Master",
                "devices_before": devices_before,
                "devices_after": devices_after,
                "new_devices": new_devices,
                "uri": item_uri,
            }
        except Exception as e:
            self.log_message("Error loading browser item on master: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise

    def _load_browser_item_on_return(self, return_index, item_uri):
        """Load a browser item onto a return track."""
        try:
            if return_index < 0 or return_index >= len(self._song.return_tracks):
                raise IndexError("Return index {0} out of range (0..{1})".format(
                    return_index, len(self._song.return_tracks) - 1))
            return_track = self._song.return_tracks[return_index]
            app = self.application()
            item = self._find_browser_item_by_uri(app.browser, item_uri)
            if not item:
                raise ValueError("Browser item with URI '{0}' not found".format(item_uri))
            devices_before = [d.name for d in return_track.devices]
            self._song.view.selected_track = return_track
            app.browser.load_item(item)
            devices_after = [d.name for d in return_track.devices]
            db_counter = {}
            for n in devices_before:
                db_counter[n] = db_counter.get(n, 0) + 1
            new_devices = []
            for n in devices_after:
                if db_counter.get(n, 0) > 0:
                    db_counter[n] -= 1
                else:
                    new_devices.append(n)
            return {
                "loaded": True,
                "item_name": item.name,
                "track_name": return_track.name,
                "devices_before": devices_before,
                "devices_after": devices_after,
                "new_devices": new_devices,
                "uri": item_uri,
            }
        except Exception as e:
            self.log_message("Error loading browser item on return: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise

    def _create_return_track(self):
        """Create a new return track via song.create_return_track() (Live 12)."""
        try:
            before = len(self._song.return_tracks)
            self._song.create_return_track()
            after = len(self._song.return_tracks)
            if after <= before:
                raise RuntimeError("create_return_track did not increase return track count")
            new_index = after - 1
            new_track = self._song.return_tracks[new_index]
            return {
                "created": True,
                "return_index": new_index,
                "name": new_track.name,
                "total_returns": after,
            }
        except Exception as e:
            self.log_message("Error creating return track: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise

    # ----- Live.Conversions wrappers (2026-05-17) -----
    # Validated against Live 12 stubs (Push2/convert.py). The conversion functions
    # mutate the song as a side effect (create new track/clip); we diff
    # track count before/after to return the new track's index.

    def _get_clip_at(self, track_index, clip_index):
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index {0} out of range".format(track_index))
        track = self._song.tracks[track_index]
        if clip_index < 0 or clip_index >= len(track.clip_slots):
            raise IndexError("Clip index {0} out of range on track {1}".format(clip_index, track.name))
        slot = track.clip_slots[clip_index]
        if not slot.has_clip:
            raise ValueError("No clip in slot {0} of track '{1}'".format(clip_index, track.name))
        return slot.clip

    def _find_new_track(self, snapshot_ids):
        """Given a set of track ids from BEFORE an operation, find the track
        added since. Live inserts conversion-result tracks adjacent to source,
        not at the end — so we can't just use `tracks_after - 1`."""
        for i, t in enumerate(self._song.tracks):
            if id(t) not in snapshot_ids:
                return i, t.name
        return None, None

    def _audio_to_midi_clip(self, track_index, clip_index, conversion_type):
        """Live 12 audio→MIDI transcription. conversion_type: 'melody'|'harmony'|'drums'.
        Creates a new MIDI track with the converted clip.

        IMPORTANT (validated 2026-05-17 in testing): Live's conversion APIs
        require the clip to be the currently SELECTED detail clip. We set
        view.detail_clip explicitly before invoking — mirrors Push2's flow
        where the user has already clicked the clip into detail view.
        """
        try:
            clip = self._get_clip_at(track_index, clip_index)
            type_map = {
                "melody": Live.Conversions.AudioToMidiType.melody_to_midi,
                "harmony": Live.Conversions.AudioToMidiType.harmony_to_midi,
                "drums": Live.Conversions.AudioToMidiType.drums_to_midi,
            }
            if conversion_type not in type_map:
                raise ValueError(
                    "Unknown conversion_type '{0}'. Use one of: {1}".format(
                        conversion_type, ", ".join(type_map.keys())))
            if not Live.Conversions.is_convertible_to_midi(self._song, clip):
                raise ValueError("Clip is not convertible to MIDI (must be audio)")
            # Set detail_clip to anchor the API to OUR target
            self._song.view.detail_clip = clip
            ids_before = {id(t) for t in self._song.tracks}
            tracks_before = len(self._song.tracks)
            Live.Conversions.audio_to_midi_clip(self._song, clip, type_map[conversion_type])
            tracks_after = len(self._song.tracks)
            new_track_index, new_track_name = self._find_new_track(ids_before)
            return {
                "converted": True,
                "conversion_type": conversion_type,
                "source_track": self._song.tracks[track_index].name,
                "source_clip": clip.name or "",
                "new_track_index": new_track_index,
                "new_track_name": new_track_name,
                "total_tracks": tracks_after,
            }
        except Exception as e:
            self.log_message("Error in audio_to_midi_clip: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise

    def _create_drum_rack_from_audio_clip(self, track_index, clip_index):
        """Live 12: audio clip → Drum Rack on new track.

        Sets view.detail_clip before invoking — Live's API requires the clip
        to be the currently selected detail clip (validated 2026-05-17).
        """
        try:
            clip = self._get_clip_at(track_index, clip_index)
            self._song.view.detail_clip = clip
            ids_before = {id(t) for t in self._song.tracks}
            tracks_before = len(self._song.tracks)
            Live.Conversions.create_drum_rack_from_audio_clip(self._song, clip)
            tracks_after = len(self._song.tracks)
            new_track_index, new_track_name = self._find_new_track(ids_before)
            return {
                "converted": True,
                "source_track": self._song.tracks[track_index].name,
                "source_clip": clip.name or "",
                "new_track_index": new_track_index,
                "new_track_name": new_track_name,
                "total_tracks": tracks_after,
            }
        except Exception as e:
            self.log_message("Error in create_drum_rack_from_audio_clip: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise

    def _create_midi_track_from_audio_clip(self, track_index, clip_index):
        """Live 12: audio clip → new MIDI track with Simpler loaded from the clip.

        Sets view.detail_clip before invoking (Live API requirement).
        """
        try:
            clip = self._get_clip_at(track_index, clip_index)
            self._song.view.detail_clip = clip
            ids_before = {id(t) for t in self._song.tracks}
            tracks_before = len(self._song.tracks)
            Live.Conversions.create_midi_track_with_simpler(self._song, clip)
            tracks_after = len(self._song.tracks)
            new_track_index, new_track_name = self._find_new_track(ids_before)
            return {
                "converted": True,
                "source_track": self._song.tracks[track_index].name,
                "source_clip": clip.name or "",
                "new_track_index": new_track_index,
                "new_track_name": new_track_name,
                "total_tracks": tracks_after,
            }
        except Exception as e:
            self.log_message("Error in create_midi_track_from_audio_clip: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise

    def _move_track_devices_to_drum_pad(self, track_index):
        """Live 12: move a track's devices into a new pad of a Drum Rack.
        Useful for organizing layered drum content into a single rack.
        """
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            source_name = self._song.tracks[track_index].name
            Live.Conversions.move_devices_on_track_to_new_drum_rack_pad(self._song, track_index)
            return {
                "moved": True,
                "source_track": source_name,
                "total_tracks": len(self._song.tracks),
            }
        except Exception as e:
            self.log_message("Error in move_track_devices_to_drum_pad: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise

    def _convert_sliced_simpler_to_drum_rack(self, track_index, device_index):
        """Live 12: convert a Simpler (in sliced mode) on a track into a Drum Rack."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            if device_index < 0 or device_index >= len(track.devices):
                raise IndexError("Device index out of range on track '{0}'".format(track.name))
            device = track.devices[device_index]
            Live.Conversions.sliced_simpler_to_drum_rack(self._song, device)
            return {
                "converted": True,
                "track": track.name,
                "source_device": device.name,
                "devices_after": [d.name for d in track.devices],
            }
        except Exception as e:
            self.log_message("Error in convert_sliced_simpler_to_drum_rack: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise

    def _find_browser_item_by_uri(self, browser_or_item, uri, max_depth=10, current_depth=0):
        """Find a browser item by its URI"""
        try:
            # Check if this is the item we're looking for
            if hasattr(browser_or_item, 'uri') and browser_or_item.uri == uri:
                return browser_or_item
            
            # Stop recursion if we've reached max depth
            if current_depth >= max_depth:
                return None
            
            # Check if this is a browser with root categories
            if hasattr(browser_or_item, 'instruments'):
                # Check all main categories. Each is a separate top-level browser
                # node — none of them are reachable via .instruments. URIs under
                # categories not in this list will silently fail to load.
                categories = [
                    browser_or_item.instruments,
                    browser_or_item.sounds,
                    browser_or_item.drums,
                    browser_or_item.audio_effects,
                    browser_or_item.midi_effects,
                ]
                for attr in ('plugins', 'max_for_live', 'samples',
                             'user_library', 'current_project', 'packs'):
                    if hasattr(browser_or_item, attr):
                        categories.append(getattr(browser_or_item, attr))

                for category in categories:
                    item = self._find_browser_item_by_uri(category, uri, max_depth, current_depth + 1)
                    if item:
                        return item

                return None
            
            # Check if this item has children
            if hasattr(browser_or_item, 'children') and browser_or_item.children:
                for child in browser_or_item.children:
                    item = self._find_browser_item_by_uri(child, uri, max_depth, current_depth + 1)
                    if item:
                        return item
            
            return None
        except Exception as e:
            self.log_message("Error finding browser item by URI: {0}".format(str(e)))
            return None
    
    # Helper methods
    
    def _get_device_type(self, device):
        """Get the type of a device"""
        try:
            # Simple heuristic - in a real implementation you'd look at the device class
            if device.can_have_drum_pads:
                return "drum_machine"
            elif device.can_have_chains:
                return "rack"
            elif "instrument" in device.class_display_name.lower():
                return "instrument"
            elif "audio_effect" in device.class_name.lower():
                return "audio_effect"
            elif "midi_effect" in device.class_name.lower():
                return "midi_effect"
            else:
                return "unknown"
        except AttributeError:
            return "unknown"
    
    def get_browser_tree(self, category_type="all"):
        """
        Get a simplified tree of browser categories.
        
        Args:
            category_type: Type of categories to get ('all', 'instruments', 'sounds', etc.)
            
        Returns:
            Dictionary with the browser tree structure
        """
        try:
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")
                
            # Check if browser is available
            if not hasattr(app, 'browser') or app.browser is None:
                raise RuntimeError("Browser is not available in the Live application")
            
            # Log available browser attributes to help diagnose issues
            browser_attrs = [attr for attr in dir(app.browser) if not attr.startswith('_')]
            self.log_message("Available browser attributes: {0}".format(browser_attrs))
            
            result = {
                "type": category_type,
                "categories": [],
                "available_categories": browser_attrs
            }
            
            # Helper function to process a browser item and its children
            def process_item(item, depth=0):
                if not item:
                    return None
                
                result = {
                    "name": item.name if hasattr(item, 'name') else "Unknown",
                    "is_folder": hasattr(item, 'children') and bool(item.children),
                    "is_device": hasattr(item, 'is_device') and item.is_device,
                    "is_loadable": hasattr(item, 'is_loadable') and item.is_loadable,
                    "uri": item.uri if hasattr(item, 'uri') else None,
                    "children": []
                }
                
                
                return result
            
            # Process based on category type and available attributes
            if (category_type == "all" or category_type == "instruments") and hasattr(app.browser, 'instruments'):
                try:
                    instruments = process_item(app.browser.instruments)
                    if instruments:
                        instruments["name"] = "Instruments"  # Ensure consistent naming
                        result["categories"].append(instruments)
                except Exception as e:
                    self.log_message("Error processing instruments: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "sounds") and hasattr(app.browser, 'sounds'):
                try:
                    sounds = process_item(app.browser.sounds)
                    if sounds:
                        sounds["name"] = "Sounds"  # Ensure consistent naming
                        result["categories"].append(sounds)
                except Exception as e:
                    self.log_message("Error processing sounds: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "drums") and hasattr(app.browser, 'drums'):
                try:
                    drums = process_item(app.browser.drums)
                    if drums:
                        drums["name"] = "Drums"  # Ensure consistent naming
                        result["categories"].append(drums)
                except Exception as e:
                    self.log_message("Error processing drums: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "audio_effects") and hasattr(app.browser, 'audio_effects'):
                try:
                    audio_effects = process_item(app.browser.audio_effects)
                    if audio_effects:
                        audio_effects["name"] = "Audio Effects"  # Ensure consistent naming
                        result["categories"].append(audio_effects)
                except Exception as e:
                    self.log_message("Error processing audio_effects: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "midi_effects") and hasattr(app.browser, 'midi_effects'):
                try:
                    midi_effects = process_item(app.browser.midi_effects)
                    if midi_effects:
                        midi_effects["name"] = "MIDI Effects"
                        result["categories"].append(midi_effects)
                except Exception as e:
                    self.log_message("Error processing midi_effects: {0}".format(str(e)))
            
            # Try to process other potentially available categories
            for attr in browser_attrs:
                if attr not in ['instruments', 'sounds', 'drums', 'audio_effects', 'midi_effects'] and \
                   (category_type == "all" or category_type == attr):
                    try:
                        item = getattr(app.browser, attr)
                        if hasattr(item, 'children') or hasattr(item, 'name'):
                            category = process_item(item)
                            if category:
                                category["name"] = attr.capitalize()
                                result["categories"].append(category)
                    except Exception as e:
                        self.log_message("Error processing {0}: {1}".format(attr, str(e)))
            
            self.log_message("Browser tree generated for {0} with {1} root categories".format(
                category_type, len(result['categories'])))
            return result
            
        except Exception as e:
            self.log_message("Error getting browser tree: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise
    
    def get_browser_items_at_path(self, path):
        """
        Get browser items at a specific path.
        
        Args:
            path: Path in the format "category/folder/subfolder"
                 where category is one of: instruments, sounds, drums, audio_effects, midi_effects
                 or any other available browser category
                 
        Returns:
            Dictionary with items at the specified path
        """
        try:
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")
                
            # Check if browser is available
            if not hasattr(app, 'browser') or app.browser is None:
                raise RuntimeError("Browser is not available in the Live application")
            
            # Log available browser attributes to help diagnose issues
            browser_attrs = [attr for attr in dir(app.browser) if not attr.startswith('_')]
            self.log_message("Available browser attributes: {0}".format(browser_attrs))
                
            # Parse the path
            path_parts = path.split("/")
            if not path_parts:
                raise ValueError("Invalid path")
            
            # Determine the root category
            root_category = path_parts[0].lower()
            current_item = None
            
            # Check standard categories first
            if root_category == "instruments" and hasattr(app.browser, 'instruments'):
                current_item = app.browser.instruments
            elif root_category == "sounds" and hasattr(app.browser, 'sounds'):
                current_item = app.browser.sounds
            elif root_category == "drums" and hasattr(app.browser, 'drums'):
                current_item = app.browser.drums
            elif root_category == "audio_effects" and hasattr(app.browser, 'audio_effects'):
                current_item = app.browser.audio_effects
            elif root_category == "midi_effects" and hasattr(app.browser, 'midi_effects'):
                current_item = app.browser.midi_effects
            else:
                # Try to find the category in other browser attributes
                found = False
                for attr in browser_attrs:
                    if attr.lower() == root_category:
                        try:
                            current_item = getattr(app.browser, attr)
                            found = True
                            break
                        except Exception as e:
                            self.log_message("Error accessing browser attribute {0}: {1}".format(attr, str(e)))
                
                if not found:
                    # If we still haven't found the category, return available categories
                    return {
                        "path": path,
                        "error": "Unknown or unavailable category: {0}".format(root_category),
                        "available_categories": browser_attrs,
                        "items": []
                    }
            
            # Navigate through the path
            for i in range(1, len(path_parts)):
                part = path_parts[i]
                if not part:  # Skip empty parts
                    continue
                
                if not hasattr(current_item, 'children'):
                    return {
                        "path": path,
                        "error": "Item at '{0}' has no children".format('/'.join(path_parts[:i])),
                        "items": []
                    }
                
                found = False
                for child in current_item.children:
                    if hasattr(child, 'name') and child.name.lower() == part.lower():
                        current_item = child
                        found = True
                        break
                
                if not found:
                    return {
                        "path": path,
                        "error": "Path part '{0}' not found".format(part),
                        "items": []
                    }
            
            # Get items at the current path
            items = []
            if hasattr(current_item, 'children'):
                for child in current_item.children:
                    item_info = {
                        "name": child.name if hasattr(child, 'name') else "Unknown",
                        "is_folder": hasattr(child, 'children') and bool(child.children),
                        "is_device": hasattr(child, 'is_device') and child.is_device,
                        "is_loadable": hasattr(child, 'is_loadable') and child.is_loadable,
                        "uri": child.uri if hasattr(child, 'uri') else None
                    }
                    items.append(item_info)
            
            result = {
                "path": path,
                "name": current_item.name if hasattr(current_item, 'name') else "Unknown",
                "uri": current_item.uri if hasattr(current_item, 'uri') else None,
                "is_folder": hasattr(current_item, 'children') and bool(current_item.children),
                "is_device": hasattr(current_item, 'is_device') and current_item.is_device,
                "is_loadable": hasattr(current_item, 'is_loadable') and current_item.is_loadable,
                "items": items
            }
            
            self.log_message("Retrieved {0} items at path: {1}".format(len(items), path))
            return result
            
        except Exception as e:
            self.log_message("Error getting browser items at path: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise

    def _get_full_session(self, include_params=True):
        """Return the entire session state in one call."""
        try:
            session = self._get_session_info()

            tracks = []
            for i in range(len(self._song.tracks)):
                t = self._get_track_info(i)
                if include_params:
                    for dev in t.get("devices", []):
                        try:
                            params = self._get_device_parameters(i, dev["index"])
                            dev["parameters"] = params.get("parameters", [])
                        except Exception:
                            dev["parameters"] = []
                tracks.append(t)

            return_tracks = []
            for i in range(len(self._song.return_tracks)):
                rt = self._get_return_track_info(i)
                if include_params:
                    for dev in rt.get("devices", []):
                        try:
                            rt_obj = self._song.return_tracks[i]
                            params_list = []
                            for j, p in enumerate(rt_obj.devices[dev["index"]].parameters):
                                params_list.append({
                                    "index": j,
                                    "name": p.name,
                                    "value": p.value,
                                    "min": p.min,
                                    "max": p.max,
                                    "is_enabled": p.is_enabled,
                                })
                            dev["parameters"] = params_list
                        except Exception:
                            dev["parameters"] = []
                return_tracks.append(rt)

            master_track = self._song.master_track
            master_devices = []
            for j, d in enumerate(master_track.devices):
                dev_info = {
                    "index": j,
                    "name": d.name,
                    "class_name": d.class_name,
                    "type": self._get_device_type(d),
                }
                if include_params:
                    dev_info["parameters"] = [
                        {"index": k, "name": p.name, "value": p.value,
                         "min": p.min, "max": p.max, "is_enabled": p.is_enabled}
                        for k, p in enumerate(d.parameters)
                    ]
                master_devices.append(dev_info)

            master = {
                "name": master_track.name,
                "volume": master_track.mixer_device.volume.value,
                "panning": master_track.mixer_device.panning.value,
                "devices": master_devices,
            }

            return {
                "session": session,
                "tracks": tracks,
                "return_tracks": return_tracks,
                "master_track": master,
            }
        except Exception as e:
            self.log_message("Error getting full session: " + str(e))
            raise

    # ---------------- Clip envelope helpers ----------------

    def _resolve_envelope_parameter(self, track, param_path):
        """Resolve a string param_path to a (parameter, description) tuple.

        Accepted forms:
        - "mixer.volume" / "mixer.panning" / "mixer.send:N"
        - "device:N.parameter:M"          (device index + parameter index)
        - "device:N.<param_name>"         (device index + parameter name)
        """
        if not isinstance(param_path, str) or "." not in param_path:
            raise ValueError("param_path must be 'mixer.X' or 'device:N.Y', got '{0}'".format(param_path))
        head, tail = param_path.split(".", 1)

        if head.lower() == "mixer":
            mixer = track.mixer_device
            key = tail.lower()
            if key == "volume":
                return mixer.volume, "mixer.volume"
            if key in ("panning", "pan"):
                return mixer.panning, "mixer.panning"
            if key.startswith("send:"):
                try:
                    send_idx = int(key.split(":", 1)[1])
                except (ValueError, IndexError):
                    raise ValueError("Bad send spec '{0}'".format(tail))
                if send_idx < 0 or send_idx >= len(mixer.sends):
                    raise IndexError("Send index {0} out of range (0..{1})".format(
                        send_idx, len(mixer.sends) - 1))
                return mixer.sends[send_idx], "mixer.send:{0}".format(send_idx)
            raise ValueError("Unknown mixer param '{0}' (use volume/panning/send:N)".format(tail))

        if head.lower().startswith("device:"):
            try:
                device_idx = int(head.split(":", 1)[1])
            except (ValueError, IndexError):
                raise ValueError("Bad device spec '{0}'".format(head))
            if device_idx < 0 or device_idx >= len(track.devices):
                raise IndexError("Device index {0} out of range".format(device_idx))
            device = track.devices[device_idx]
            if tail.lower().startswith("parameter:"):
                try:
                    key = int(tail.split(":", 1)[1])
                except (ValueError, IndexError):
                    raise ValueError("Bad parameter spec '{0}'".format(tail))
            else:
                key = tail
            param, _ = self._resolve_parameter(device, key)
            return param, "device:{0}.{1}".format(device_idx, param.name)

        raise ValueError("param_path head must be 'mixer' or 'device:N', got '{0}'".format(head))

    def _get_clip_for_envelope(self, track_index, clip_index, location="session"):
        """Bounds-check track + clip; raise if missing. Returns (track, clip).

        location:
          'session' (default) -> track.clip_slots[clip_index].clip
          'arrangement'       -> track.arrangement_clips[clip_index]
        """
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        loc = (location or "session").lower()
        if loc == "arrangement":
            arr_clips = list(track.arrangement_clips)
            if clip_index < 0 or clip_index >= len(arr_clips):
                raise IndexError("Arrangement clip index {0} out of range (0..{1})".format(
                    clip_index, len(arr_clips) - 1))
            return track, arr_clips[clip_index]
        if loc != "session":
            raise ValueError("location must be 'session' or 'arrangement', got '{0}'".format(location))
        if clip_index < 0 or clip_index >= len(track.clip_slots):
            raise IndexError("Clip slot index out of range")
        slot = track.clip_slots[clip_index]
        if not slot.has_clip:
            raise Exception("No clip in slot {0} of track {1}".format(clip_index, track_index))
        return track, slot.clip

    def _get_clip_envelope(self, track_index, clip_index, param_path,
                           sample_interval=0.25, times=None, location="session"):
        """Read an envelope by sampling value_at_time across the clip length.

        LOM doesn't expose envelope points directly — we sample. By default
        every 0.25 beats; pass `times` to specify exact sample positions.
        location: 'session' (default) or 'arrangement'.
        Returns {parameter, exists, samples:[{time, value}, ...]}.
        """
        try:
            track, clip = self._get_clip_for_envelope(track_index, clip_index, location)
            param, desc = self._resolve_envelope_parameter(track, param_path)
            envelope = clip.automation_envelope(param)
            base = {
                "track_index": track_index,
                "clip_index": clip_index,
                "parameter": desc,
                "param_min": param.min,
                "param_max": param.max,
                "clip_length": float(clip.length),
            }
            if envelope is None:
                base.update({"exists": False, "samples": []})
                return base
            if times is None:
                length = float(clip.length)
                step = max(0.001, float(sample_interval))
                n = int(length / step) + 1
                times = [i * step for i in range(n)]
                if not times or times[-1] < length:
                    times.append(length)
            samples = []
            for t in times:
                tt = float(t)
                samples.append({"time": tt, "value": float(envelope.value_at_time(tt))})
            base.update({"exists": True, "samples": samples})
            return base
        except Exception as e:
            self.log_message("Error getting clip envelope: " + str(e))
            raise

    def _set_clip_envelope_point(self, track_index, clip_index, param_path,
                                 time, value, length=0.0, location="session"):
        """Insert a single step at given time. Creates envelope on first write."""
        try:
            track, clip = self._get_clip_for_envelope(track_index, clip_index, location)
            param, desc = self._resolve_envelope_parameter(track, param_path)
            envelope = clip.automation_envelope(param)
            if envelope is None:
                envelope = clip.create_automation_envelope(param)
            if envelope is None:
                raise Exception("Could not create envelope for '{0}'".format(desc))
            v = float(value)
            clamped = max(param.min, min(param.max, v))
            envelope.insert_step(float(time), float(length), clamped)
            return {
                "track_index": track_index,
                "clip_index": clip_index,
                "parameter": desc,
                "time": float(time),
                "length": float(length),
                "value": clamped,
                "clamped": clamped != v,
            }
        except Exception as e:
            self.log_message("Error setting clip envelope point: " + str(e))
            raise

    def _set_clip_envelope_curve(self, track_index, clip_index, param_path,
                                 points, replace=True, location="session"):
        """Bulk-write a curve. Each point is dict {time, value, length?}.

        If replace=True (default), clears any existing envelope on the parameter
        first. Each point becomes an `insert_step` call.
        location: 'session' (default) or 'arrangement'.
        """
        try:
            track, clip = self._get_clip_for_envelope(track_index, clip_index, location)
            param, desc = self._resolve_envelope_parameter(track, param_path)
            if replace:
                try:
                    clip.clear_envelope(param)
                except Exception:
                    pass
            envelope = clip.automation_envelope(param)
            if envelope is None:
                envelope = clip.create_automation_envelope(param)
            if envelope is None:
                raise Exception("Could not create envelope for '{0}'".format(desc))
            inserted = 0
            clamped_count = 0
            for pt in points:
                t = float(pt.get("time", 0.0))
                v = float(pt.get("value", 0.0))
                ln = float(pt.get("length", 0.0))
                cl = max(param.min, min(param.max, v))
                if cl != v:
                    clamped_count += 1
                envelope.insert_step(t, ln, cl)
                inserted += 1
            return {
                "track_index": track_index,
                "clip_index": clip_index,
                "parameter": desc,
                "points_inserted": inserted,
                "clamped_count": clamped_count,
                "replaced": replace,
            }
        except Exception as e:
            self.log_message("Error setting clip envelope curve: " + str(e))
            raise

    def _re_enable_automation(self, track_index=None, device_index=None, parameter=None):
        """Re-enable automation. With no args, re-enables song-wide
        (covers all 'overridden' params). With track_index+device_index+parameter,
        re-enables a single parameter.
        """
        try:
            if track_index is None:
                self._song.re_enable_automation()
                return {"scope": "global"}
            track, device = self._get_device(track_index, device_index)
            param, _ = self._resolve_parameter(device, parameter)
            param.re_enable_automation()
            return {
                "scope": "parameter",
                "track_index": track_index,
                "device_index": device_index,
                "parameter": param.name,
                "automation_state": int(param.automation_state),
            }
        except Exception as e:
            self.log_message("Error re-enabling automation: " + str(e))
            raise

    def _get_parameter_automation_state(self, track_index, device_index, parameter):
        """Read automation_state of a device parameter (0=none, 1=played, 2=overridden)."""
        try:
            _, device = self._get_device(track_index, device_index)
            param, idx = self._resolve_parameter(device, parameter)
            return {
                "track_index": track_index,
                "device_index": device_index,
                "parameter_index": idx,
                "parameter": param.name,
                "automation_state": int(param.automation_state),
            }
        except Exception as e:
            self.log_message("Error reading automation state: " + str(e))
            raise

    # ---------------- Rack chain / drum pad helpers ----------------

    def _require_rack(self, track_index, device_index, kind="any"):
        """Bounds-check + ensure device is a rack. kind: 'any' | 'drum'.
        Returns (track, device).
        """
        track, device = self._get_device(track_index, device_index)
        if not getattr(device, "can_have_chains", False):
            raise Exception("Device '{0}' is not a rack (can_have_chains=False)".format(device.name))
        if kind == "drum" and not getattr(device, "can_have_drum_pads", False):
            raise Exception("Device '{0}' is not a drum rack (can_have_drum_pads=False)".format(device.name))
        return track, device

    def _summarize_chain(self, chain, index):
        mixer = chain.mixer_device
        return {
            "index": index,
            "name": chain.name,
            "mute": bool(chain.mute),
            "solo": bool(chain.solo),
            "color_index": int(getattr(chain, "color_index", -1)),
            "volume": mixer.volume.value,
            "panning": mixer.panning.value,
            "sends": [s.value for s in mixer.sends],
            "device_count": len(chain.devices),
            "devices": [
                {"index": i, "name": d.name, "class_name": d.class_name}
                for i, d in enumerate(chain.devices)
            ],
        }

    def _get_rack_chains(self, track_index, device_index):
        """List all chains on a rack device."""
        try:
            _, device = self._require_rack(track_index, device_index, "any")
            chains = list(device.chains)
            return {
                "track_index": track_index,
                "device_index": device_index,
                "rack_name": device.name,
                "is_drum_rack": bool(getattr(device, "can_have_drum_pads", False)),
                "chain_count": len(chains),
                "chains": [self._summarize_chain(c, i) for i, c in enumerate(chains)],
            }
        except Exception as e:
            self.log_message("Error getting rack chains: " + str(e))
            raise

    def _get_drum_pads(self, track_index, device_index, only_non_empty=True):
        """List drum pads on a drum rack device.

        DrumPads are indexed by MIDI note (0-127). If only_non_empty is True
        (default), skip pads with no chain (most are empty in a typical kit).
        Each pad's `chain_index` refers to its position in `device.chains` so
        callers can use `set_chain_*` tools on it.
        """
        try:
            _, device = self._require_rack(track_index, device_index, "drum")
            pads = list(device.drum_pads)
            # Cache device.chains once and use LOM equality (==) to match each
            # pad's chain. id() doesn't work — LOM wrappers are fresh per access.
            device_chains = list(device.chains)
            pad_dicts = []
            for pad in pads:
                pad_chains = list(pad.chains)
                if only_non_empty and len(pad_chains) == 0:
                    continue
                chain_idx = -1
                if pad_chains:
                    target = pad_chains[0]
                    for i, c in enumerate(device_chains):
                        if c == target:
                            chain_idx = i
                            break
                pad_dicts.append({
                    "note": int(pad.note),
                    "name": pad.name or "",
                    "mute": bool(pad.mute),
                    "solo": bool(pad.solo),
                    "chain_count": len(pad_chains),
                    "chain_index": chain_idx,
                    "devices": [
                        {"index": i, "name": d.name, "class_name": d.class_name}
                        for i, d in enumerate(pad_chains[0].devices)
                    ] if pad_chains else [],
                })
            return {
                "track_index": track_index,
                "device_index": device_index,
                "rack_name": device.name,
                "pad_count": len(pad_dicts),
                "only_non_empty": bool(only_non_empty),
                "pads": pad_dicts,
            }
        except Exception as e:
            self.log_message("Error getting drum pads: " + str(e))
            raise

    def _resolve_chain(self, track_index, device_index, chain_index):
        _, device = self._require_rack(track_index, device_index, "any")
        chains = list(device.chains)
        if chain_index < 0 or chain_index >= len(chains):
            raise IndexError("Chain index {0} out of range (0..{1})".format(
                chain_index, len(chains) - 1))
        return device, chains[chain_index]

    def _set_chain_state(self, track_index, device_index, chain_index, attribute, value):
        """Toggle mute/solo on a rack chain. attribute in {'mute','solo'}, value bool."""
        try:
            _, chain = self._resolve_chain(track_index, device_index, chain_index)
            attr = attribute.lower()
            if attr not in ("mute", "solo"):
                raise ValueError("attribute must be 'mute' or 'solo', got '{0}'".format(attribute))
            setattr(chain, attr, bool(value))
            return {
                "track_index": track_index,
                "device_index": device_index,
                "chain_index": chain_index,
                "name": chain.name,
                "attribute": attr,
                "value": bool(getattr(chain, attr)),
            }
        except Exception as e:
            self.log_message("Error setting chain state: " + str(e))
            raise

    def _set_chain_mixer_value(self, track_index, device_index, chain_index, param, value):
        """Set volume/panning/send on a rack chain's mixer."""
        try:
            _, chain = self._resolve_chain(track_index, device_index, chain_index)
            mixer = chain.mixer_device
            key = param.lower() if isinstance(param, str) else param
            if key == "volume":
                target = mixer.volume
            elif key in ("panning", "pan"):
                target = mixer.panning
            elif isinstance(key, str) and key.startswith("send:"):
                try:
                    send_idx = int(key.split(":", 1)[1])
                except (ValueError, IndexError):
                    raise ValueError("Bad send spec '{0}'".format(param))
                if send_idx < 0 or send_idx >= len(mixer.sends):
                    raise IndexError("Send index {0} out of range (0..{1})".format(
                        send_idx, len(mixer.sends) - 1))
                target = mixer.sends[send_idx]
            else:
                raise ValueError("Unknown mixer param '{0}'. Use 'volume', 'panning', or 'send:N'".format(param))
            clamped = max(target.min, min(target.max, float(value)))
            target.value = clamped
            return {
                "track_index": track_index,
                "device_index": device_index,
                "chain_index": chain_index,
                "name": chain.name,
                "param": param,
                "value": target.value,
                "clamped": clamped != float(value),
            }
        except Exception as e:
            self.log_message("Error setting chain mixer value: " + str(e))
            raise

    def _set_drum_pad_state(self, track_index, device_index, pad_note, attribute, value):
        """Toggle mute/solo on a drum rack pad (addressed by MIDI note)."""
        try:
            _, device = self._require_rack(track_index, device_index, "drum")
            note = int(pad_note)
            if note < 0 or note > 127:
                raise ValueError("pad_note must be 0..127, got {0}".format(pad_note))
            pads = list(device.drum_pads)
            pad = pads[note]
            attr = attribute.lower()
            if attr not in ("mute", "solo"):
                raise ValueError("attribute must be 'mute' or 'solo', got '{0}'".format(attribute))
            setattr(pad, attr, bool(value))
            return {
                "track_index": track_index,
                "device_index": device_index,
                "pad_note": note,
                "pad_name": pad.name or "",
                "attribute": attr,
                "value": bool(getattr(pad, attr)),
                "is_empty": len(list(pad.chains)) == 0,
            }
        except Exception as e:
            self.log_message("Error setting drum pad state: " + str(e))
            raise

    # ---------------- High-value 6 (2026-05-17) ----------------
    # Scale, quantize, cue points, grooves, warp, selection. Wires the
    # Live 12 API surface that the toolkit was previously missing.

    _NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

    # ---- Scale ----

    def _get_song_scale(self):
        """Read the Live 12 global scale/key.

        Live 12 added Song.scale_name (str), Song.root_note (int 0..11),
        Song.in_key (bool). Older Live versions raise AttributeError on these.

        Note: On Live 12.3.7, `in_key` attr exists (hasattr=True) but reads
        as None until toggled in UI — verified 2026-05-17. Not a code bug.
        Writing it via set_song_scale(in_key=True/False) works fine.
        """
        try:
            song = self._song
            scale_name = getattr(song, "scale_name", None)
            root_note = getattr(song, "root_note", None)
            in_key_raw = getattr(song, "in_key", None)
            if scale_name is None and root_note is None:
                raise RuntimeError("Song.scale_name/root_note not available — Live 12 required")
            return {
                "scale_name": scale_name,
                "root_note": root_note,
                "root_name": self._NOTE_NAMES[int(root_note) % 12] if root_note is not None else None,
                "in_key": bool(in_key_raw) if in_key_raw is not None else None,
                "in_key_raw": in_key_raw,  # None means UI never toggled it; not an error
            }
        except Exception as e:
            self.log_message("Error reading song scale: " + str(e))
            raise

    def _set_song_scale(self, scale_name=None, root_note=None, in_key=None):
        """Set the Live 12 global scale/key. Any field may be omitted to keep current.

        FIX 2026-05-17: Live's `root_note` setter has a side effect of resetting
        `scale_name` to "Major" (verified in smoke test). To preserve user
        intent, snapshot scale_name before any write and restore it afterward
        if the caller didn't explicitly request a new scale_name.
        """
        try:
            song = self._song
            # Snapshot scale_name BEFORE any write so we can restore it if a
            # subsequent setter (root_note) clobbers it as a side effect.
            preserved_scale = None
            if scale_name is None and root_note is not None and hasattr(song, "scale_name"):
                preserved_scale = song.scale_name
            changes = {}
            if scale_name is not None:
                if not hasattr(song, "scale_name"):
                    raise RuntimeError("Song.scale_name not available — Live 12 required")
                song.scale_name = str(scale_name)
                changes["scale_name"] = song.scale_name
            if root_note is not None:
                if not hasattr(song, "root_note"):
                    raise RuntimeError("Song.root_note not available — Live 12 required")
                rn = int(root_note) % 12
                song.root_note = rn
                changes["root_note"] = song.root_note
                changes["root_name"] = self._NOTE_NAMES[rn]
            if in_key is not None:
                if not hasattr(song, "in_key"):
                    raise RuntimeError("Song.in_key not available — Live 12 required")
                song.in_key = bool(in_key)
                changes["in_key"] = bool(song.in_key)
            # Restore scale_name if root_note write clobbered it
            if preserved_scale is not None and song.scale_name != preserved_scale:
                song.scale_name = preserved_scale
                changes["scale_name_preserved"] = preserved_scale
            if not changes:
                raise ValueError("No fields provided (scale_name/root_note/in_key)")
            return {"changed": changes, "current": self._get_song_scale()}
        except Exception as e:
            self.log_message("Error setting song scale: " + str(e))
            raise

    # ---- Quantize ----

    _QUANTIZE_GRID_NAMES = {
        "none": 0, "no_q": 0,
        "1/4": 1, "quarter": 1,
        "1/8": 2, "eighth": 2,
        "1/8t": 3, "eighth_triplet": 3,
        "1/8+1/8t": 4,
        "1/16": 5, "sixteenth": 5,
        "1/16t": 6, "sixteenth_triplet": 6,
        "1/16+1/16t": 7,
        "1/32": 8, "thirtysecond": 8,
    }

    def _resolve_quantize_grid(self, grid):
        """Accept either an int enum value or a string name."""
        if isinstance(grid, (int, float)):
            return int(grid)
        key = str(grid).lower().strip()
        if key not in self._QUANTIZE_GRID_NAMES:
            valid = ", ".join(sorted(set(self._QUANTIZE_GRID_NAMES.keys())))
            raise ValueError("Unknown quantize grid '{0}'. Valid: {1}".format(grid, valid))
        return self._QUANTIZE_GRID_NAMES[key]

    def _quantize_clip_notes(self, track_index, clip_index, grid="1/16",
                              amount=1.0, quantize_pitch=False):
        """Quantize notes in a clip via Clip.quantize(grid, amount).

        - grid: int enum or string name (e.g. '1/16', '1/8t', 'none')
        - amount: 0.0..1.0 (1.0 = full quantize)
        - quantize_pitch: if True, also call Clip.quantize_pitch when available
        """
        try:
            clip = self._get_clip_at(track_index, clip_index)
            if clip.is_audio_clip:
                raise ValueError("quantize requires a MIDI clip, got audio clip")
            grid_val = self._resolve_quantize_grid(grid)
            amt = max(0.0, min(1.0, float(amount)))
            clip.quantize(grid_val, amt)
            pitch_done = False
            if quantize_pitch and hasattr(clip, "quantize_pitch"):
                clip.quantize_pitch(grid_val, amt)
                pitch_done = True
            return {
                "track_index": track_index,
                "clip_index": clip_index,
                "name": clip.name,
                "grid": grid_val,
                "amount": amt,
                "quantize_pitch_applied": pitch_done,
            }
        except Exception as e:
            self.log_message("Error quantizing clip: " + str(e))
            raise

    # ---- Cue points ----

    def _get_cue_points(self):
        """List all cue points (Song.cue_points)."""
        try:
            cues = []
            for i, cue in enumerate(self._song.cue_points):
                cues.append({
                    "index": i,
                    "name": cue.name,
                    "time": cue.time,
                })
            return {
                "count": len(cues),
                "cue_points": cues,
                "can_jump_to_next": bool(getattr(self._song, "can_jump_to_next_cue", False)),
                "can_jump_to_prev": bool(getattr(self._song, "can_jump_to_prev_cue", False)),
            }
        except Exception as e:
            self.log_message("Error reading cue points: " + str(e))
            raise

    def _set_or_delete_cue(self, time=None, name=None):
        """Toggle a cue point at the current playback head.

        LIVE API LIMITATION (verified 2026-05-17 on Live 12.3.7): there is NO
        way to create a cue at an arbitrary time programmatically. Live's
        `set_or_delete_cue()` operates at `current_song_time`, which is
        read-only when transport is stopped — `current_song_time =`,
        `start_time =`, and `jump_by()` all fail to move it. The cue is
        always created at wherever the playhead last left off.

        Workarounds for the user: scrub Live's UI cursor to the desired
        time before calling this, then call without `time`. Or start
        playback, let it reach the desired position, then call.

        We still ATTEMPT the `time` write (it's a no-op rather than an
        error) and report `transport_state` so callers can see the actual
        position the cue was created at.
        """
        try:
            song = self._song
            requested_time = None
            time_warning = None
            transport_state = None
            if time is not None:
                requested_time = float(time)
                before_cst = float(song.current_song_time)
                is_playing = bool(song.is_playing)
                # Best-effort writes; current_song_time write is silently
                # ignored when stopped, but try anyway in case playback IS on.
                try:
                    song.current_song_time = requested_time
                    if not is_playing and hasattr(song, "start_time"):
                        song.start_time = requested_time
                except Exception as e:
                    self.log_message("playhead write failed: " + str(e))
                actual_cst = float(song.current_song_time)
                transport_state = {
                    "is_playing": is_playing,
                    "before_current_song_time": before_cst,
                    "after_current_song_time": actual_cst,
                }
                if abs(actual_cst - requested_time) > 0.001:
                    time_warning = (
                        "current_song_time write blocked (read-only when "
                        "transport stopped on Live 12). Cue will land at "
                        "{0}, not requested {1}. Scrub Live's UI cursor "
                        "first to position the playhead.").format(
                        actual_cst, requested_time)
            before_ids = {id(c) for c in song.cue_points}
            song.set_or_delete_cue()
            after = list(song.cue_points)
            created = None
            for c in after:
                if id(c) not in before_ids:
                    created = c
                    break
            deleted = len(after) < len(before_ids)
            if created is not None and name is not None:
                created.name = str(name)
            result = {
                "action": "created" if created else ("deleted" if deleted else "noop"),
                "cue_time": created.time if created else None,
                "cue_name": created.name if created else None,
                "total_cues": len(after),
            }
            if requested_time is not None:
                result["requested_time"] = requested_time
            if time_warning:
                result["warning"] = time_warning
            if transport_state is not None:
                result["transport_state"] = transport_state
            return result
        except Exception as e:
            self.log_message("Error toggling cue: " + str(e))
            raise

    def _jump_to_cue(self, direction="next"):
        """Jump to next or previous cue point."""
        try:
            d = direction.lower()
            if d == "next":
                if not getattr(self._song, "can_jump_to_next_cue", True):
                    return {"jumped": False, "reason": "no next cue"}
                self._song.jump_to_next_cue()
            elif d in ("prev", "previous"):
                if not getattr(self._song, "can_jump_to_prev_cue", True):
                    return {"jumped": False, "reason": "no previous cue"}
                self._song.jump_to_prev_cue()
            else:
                raise ValueError("direction must be 'next' or 'prev'")
            return {
                "jumped": True,
                "direction": d,
                "current_song_time": self._song.current_song_time,
            }
        except Exception as e:
            self.log_message("Error jumping to cue: " + str(e))
            raise

    def _delete_cue_by_index(self, cue_index):
        """Delete a cue point by index. Uses CuePoint.jump() to move the
        playhead (which DOES update current_song_time, unlike direct writes
        when stopped), then calls set_or_delete_cue() to delete.
        """
        try:
            cues = list(self._song.cue_points)
            if cue_index < 0 or cue_index >= len(cues):
                raise IndexError("cue_index {0} out of range (have {1} cues)".format(
                    cue_index, len(cues)))
            target = cues[cue_index]
            target_time = target.time
            target_name = target.name
            # CuePoint.jump() moves the playhead INCLUDING current_song_time —
            # the workaround for the read-only-when-stopped quirk.
            target.jump()
            self._song.set_or_delete_cue()
            after = list(self._song.cue_points)
            return {
                "deleted": True,
                "cue_time": target_time,
                "cue_name": target_name,
                "total_cues_after": len(after),
            }
        except Exception as e:
            self.log_message("Error deleting cue by index: " + str(e))
            raise

    # ---- Grooves ----

    # Live 12 Groove attributes. Note: `amount` is NOT a per-groove property —
    # it's `Song.groove_amount` (global). The remaining 5 are direct on Groove
    # per Live API docs, but smoke test 2026-05-17 showed `timing` and
    # `random` not coming through on Live 12.3.7. Causes (theories):
    #  - getattr raises (silently swallowed before patch)
    #  - properties exposed as DeviceParameters not Python attrs
    # Patched 2026-05-17 to log errors AND surface what's available.
    _GROOVE_FIELDS = ("timing", "quantization_amount",
                      "random", "velocity_amount", "base")

    def _summarize_groove(self, groove, index=None):
        out = {"index": index, "name": getattr(groove, "name", "")}
        attr_errors = {}
        for f in self._GROOVE_FIELDS:
            if hasattr(groove, f):
                try:
                    out[f] = getattr(groove, f)
                except Exception as e:
                    attr_errors[f] = "getattr_raised:" + str(e)
            else:
                attr_errors[f] = "no_attr"
        # Also check if groove exposes a `parameters` collection (some Live
        # objects expose params as DeviceParameter instead of direct attrs).
        if hasattr(groove, "parameters"):
            try:
                params = list(groove.parameters)
                out["parameters"] = [
                    {"name": p.name, "value": p.value,
                     "min": p.min, "max": p.max}
                    for p in params
                ]
            except Exception as e:
                attr_errors["parameters"] = str(e)
        if attr_errors:
            out["_missing"] = attr_errors
        return out

    def _get_grooves(self):
        """List grooves in the song's groove pool.

        Also surfaces Song.groove_amount (the global groove-strength fader).
        """
        try:
            pool = getattr(self._song, "groove_pool", None)
            if pool is None:
                raise RuntimeError("Song.groove_pool not available on this Live version")
            grooves = list(pool.grooves)
            return {
                "count": len(grooves),
                "global_groove_amount": getattr(self._song, "groove_amount", None),
                "grooves": [self._summarize_groove(g, i) for i, g in enumerate(grooves)],
            }
        except Exception as e:
            self.log_message("Error reading grooves: " + str(e))
            raise

    def _set_groove_params(self, groove_index, **fields):
        """Set fields on a groove. Valid fields: amount, timing,
        quantization_amount, random, velocity_amount, base."""
        try:
            pool = self._song.groove_pool
            grooves = list(pool.grooves)
            if groove_index < 0 or groove_index >= len(grooves):
                raise IndexError("groove_index {0} out of range".format(groove_index))
            g = grooves[groove_index]
            changed = {}
            for f, v in fields.items():
                if v is None:
                    continue
                if f not in self._GROOVE_FIELDS:
                    raise ValueError("Unknown groove field '{0}'. Valid: {1}".format(
                        f, ", ".join(self._GROOVE_FIELDS)))
                if not hasattr(g, f):
                    continue
                setattr(g, f, float(v) if f != "base" else v)
                changed[f] = getattr(g, f)
            return {
                "groove_index": groove_index,
                "name": g.name,
                "changed": changed,
                "groove": self._summarize_groove(g, groove_index),
            }
        except Exception as e:
            self.log_message("Error setting groove params: " + str(e))
            raise

    def _assign_groove_to_clip(self, track_index, clip_index, groove_index):
        """Assign a pool groove to a clip (Clip.groove).

        LIVE API LIMITATION (Live 12.3.7, verified 2026-05-17): clearing
        a groove via `clip.groove = None` is rejected by Live's C++ binding:
            None.None(Clip, NoneType) did not match C++ signature:
            None(TPyHandle<AClip>, TPyHandle<AAbstractGroove>)
        There's no exposed sentinel "empty groove" object either. To
        clear, the user must right-click the groove dropdown in Live's
        clip view and select "(none)" manually.
        """
        try:
            clip = self._get_clip_at(track_index, clip_index)
            if groove_index is None or int(groove_index) < 0:
                raise NotImplementedError(
                    "Clearing a clip's groove via LOM is not supported on "
                    "Live 12.3.7 (clip.groove = None rejected by C++ binding). "
                    "Clear manually via clip view's groove dropdown.")
            grooves = list(self._song.groove_pool.grooves)
            if groove_index >= len(grooves):
                raise IndexError("groove_index out of range")
            clip.groove = grooves[groove_index]
            return {
                "track_index": track_index,
                "clip_index": clip_index,
                "name": clip.name,
                "groove_index": groove_index,
                "groove_name": grooves[groove_index].name,
            }
        except Exception as e:
            self.log_message("Error assigning groove: " + str(e))
            raise

    # ---- Clip warping ----

    def _get_clip_warp(self, track_index, clip_index):
        """Read warping state of an audio clip. Errors on MIDI clips."""
        try:
            clip = self._get_clip_at(track_index, clip_index)
            if not clip.is_audio_clip:
                raise ValueError("warp info requires an audio clip, got MIDI clip")
            mode = getattr(clip, "warp_mode", None)
            warping = getattr(clip, "warping", None)
            available = []
            if hasattr(clip, "available_warp_modes"):
                try:
                    available = list(clip.available_warp_modes)
                except Exception:
                    available = []
            return {
                "track_index": track_index,
                "clip_index": clip_index,
                "name": clip.name,
                "warping": bool(warping) if warping is not None else None,
                "warp_mode": int(mode) if mode is not None else None,
                "warp_mode_name": self._warp_mode_name(int(mode)) if mode is not None else None,
                "available_warp_modes": [int(m) for m in available],
            }
        except Exception as e:
            self.log_message("Error reading clip warp: " + str(e))
            raise

    _WARP_MODE_NAMES = {
        0: "Beats", 1: "Tones", 2: "Texture", 3: "Repitch",
        4: "Complex", 5: "REX", 6: "Complex Pro",
    }

    def _warp_mode_name(self, mode_int):
        return self._WARP_MODE_NAMES.get(mode_int, "Unknown({0})".format(mode_int))

    def _resolve_warp_mode(self, mode):
        if isinstance(mode, (int, float)):
            return int(mode)
        key = str(mode).strip().lower()
        for k, v in self._WARP_MODE_NAMES.items():
            if v.lower() == key:
                return k
        # Allow common aliases
        aliases = {"complex_pro": 6, "complexpro": 6, "complex pro": 6}
        if key in aliases:
            return aliases[key]
        raise ValueError("Unknown warp mode '{0}'. Valid: {1}".format(
            mode, ", ".join(self._WARP_MODE_NAMES.values())))

    def _set_clip_warping(self, track_index, clip_index, warping):
        try:
            clip = self._get_clip_at(track_index, clip_index)
            if not clip.is_audio_clip:
                raise ValueError("warping requires an audio clip")
            clip.warping = bool(warping)
            return {
                "track_index": track_index,
                "clip_index": clip_index,
                "name": clip.name,
                "warping": bool(clip.warping),
            }
        except Exception as e:
            self.log_message("Error setting clip warping: " + str(e))
            raise

    def _set_warp_mode(self, track_index, clip_index, mode):
        try:
            clip = self._get_clip_at(track_index, clip_index)
            if not clip.is_audio_clip:
                raise ValueError("warp_mode requires an audio clip")
            mode_int = self._resolve_warp_mode(mode)
            # Validate against available_warp_modes if exposed
            if hasattr(clip, "available_warp_modes"):
                try:
                    avail = [int(m) for m in clip.available_warp_modes]
                    if avail and mode_int not in avail:
                        self.log_message("WARN: mode {0} not in available {1}".format(mode_int, avail))
                except Exception:
                    pass
            clip.warp_mode = mode_int
            return {
                "track_index": track_index,
                "clip_index": clip_index,
                "name": clip.name,
                "warp_mode": int(clip.warp_mode),
                "warp_mode_name": self._warp_mode_name(int(clip.warp_mode)),
            }
        except Exception as e:
            self.log_message("Error setting warp mode: " + str(e))
            raise

    # ---- Selection (view introspection) ----

    def _get_selection(self):
        """Read what the user (or last MCP write) has selected in the UI."""
        try:
            view = self._song.view
            sel = {}
            try:
                t = view.selected_track
                if t is not None:
                    tracks = list(self._song.tracks)
                    try:
                        idx = tracks.index(t)
                        sel["selected_track"] = {"index": idx, "name": t.name, "kind": "track"}
                    except ValueError:
                        # Could be return or master
                        returns = list(self._song.return_tracks)
                        if t in returns:
                            sel["selected_track"] = {"index": returns.index(t), "name": t.name, "kind": "return"}
                        elif t is self._song.master_track:
                            sel["selected_track"] = {"index": -1, "name": "Master", "kind": "master"}
                        else:
                            sel["selected_track"] = {"name": t.name, "kind": "unknown"}
            except Exception:
                pass
            try:
                s = view.selected_scene
                if s is not None:
                    scenes = list(self._song.scenes)
                    sel["selected_scene"] = {"index": scenes.index(s), "name": s.name}
            except Exception:
                pass
            try:
                clip = view.detail_clip
                if clip is not None:
                    sel["detail_clip"] = {"name": clip.name, "is_audio": bool(clip.is_audio_clip)}
            except Exception:
                pass
            try:
                slot = view.highlighted_clip_slot
                if slot is not None:
                    sel["highlighted_clip_slot"] = {"has_clip": bool(slot.has_clip)}
            except Exception:
                pass
            try:
                p = view.selected_parameter
                if p is not None:
                    sel["selected_parameter"] = {"name": p.name, "value": p.value}
            except Exception:
                pass
            try:
                ch = view.selected_chain
                if ch is not None:
                    sel["selected_chain"] = {"name": ch.name}
            except Exception:
                pass
            return sel
        except Exception as e:
            self.log_message("Error reading selection: " + str(e))
            raise

    # ---------------- Warp markers batch (2026-05-17) ----------------
    # WarpMarker: each has .sample_time (audio sample position) and
    # .beat_time (clip-time position). Editing these reshapes how Live
    # time-stretches the audio.

    def _get_warp_markers(self, track_index, clip_index):
        """List all warp markers on an audio clip."""
        try:
            clip = self._get_clip_at(track_index, clip_index)
            if not clip.is_audio_clip:
                raise ValueError("warp markers require audio clip, got MIDI")
            if not hasattr(clip, "warp_markers"):
                raise NotImplementedError("Clip.warp_markers not available")
            markers = []
            for i, m in enumerate(clip.warp_markers):
                markers.append({
                    "index": i,
                    "beat_time": float(m.beat_time),
                    "sample_time": float(m.sample_time),
                })
            return {
                "track_index": track_index,
                "clip_index": clip_index,
                "name": clip.name,
                "warping": bool(getattr(clip, "warping", False)),
                "count": len(markers),
                "warp_markers": markers,
            }
        except Exception as e:
            self.log_message("Error reading warp markers: " + str(e))
            raise

    def _make_warp_marker(self, beat_time, sample_time):
        """Construct a Live.Clip.WarpMarker via the kwargs constructor.

        Pattern verified 2026-05-17 from MxDCore.py:848 —
        `Live.Clip.WarpMarker(beat_time=..., sample_time=...)`.
        """
        return Live.Clip.WarpMarker(
            beat_time=float(beat_time),
            sample_time=float(sample_time),
        )

    def _add_warp_marker(self, track_index, clip_index, beat_time, sample_time):
        """Add a warp marker at the given beat_time + sample_time position.

        FIX 2026-05-17: Live's `Clip.add_warp_marker` takes a single
        `Live.Clip.WarpMarker` object, NOT separate floats. Construct
        via kwargs.
        """
        try:
            clip = self._get_clip_at(track_index, clip_index)
            if not clip.is_audio_clip:
                raise ValueError("warp markers require audio clip")
            if not hasattr(clip, "add_warp_marker"):
                raise NotImplementedError("Clip.add_warp_marker not available")
            before = len(list(clip.warp_markers))
            marker = self._make_warp_marker(beat_time, sample_time)
            clip.add_warp_marker(marker)
            after = list(clip.warp_markers)
            return {
                "track_index": track_index,
                "clip_index": clip_index,
                "added": True,
                "beat_time": float(beat_time),
                "sample_time": float(sample_time),
                "markers_before": before,
                "markers_after": len(after),
            }
        except Exception as e:
            self.log_message("Error adding warp marker: " + str(e))
            raise

    def _remove_warp_marker(self, track_index, clip_index, beat_time):
        """Remove the warp marker at the given beat_time.

        SIGNATURE NOTE 2026-05-17: Verified empirically that the THREE
        warp-marker methods have DIFFERENT signatures:
        - add_warp_marker(WarpMarker object)
        - remove_warp_marker(beat_time: float)
        - move_warp_marker(beat_time: float, delta: float)
        """
        try:
            clip = self._get_clip_at(track_index, clip_index)
            if not clip.is_audio_clip:
                raise ValueError("warp markers require audio clip")
            if not hasattr(clip, "remove_warp_marker"):
                raise NotImplementedError("Clip.remove_warp_marker not available")
            before = len(list(clip.warp_markers))
            clip.remove_warp_marker(float(beat_time))
            after = list(clip.warp_markers)
            return {
                "track_index": track_index,
                "clip_index": clip_index,
                "removed": (len(after) < before),
                "beat_time": float(beat_time),
                "markers_before": before,
                "markers_after": len(after),
            }
        except Exception as e:
            self.log_message("Error removing warp marker: " + str(e))
            raise

    def _move_warp_marker(self, track_index, clip_index, beat_time, new_beat_time):
        """Move the warp marker at beat_time to new_beat_time.

        FIX 2026-05-17 (round 2): Unlike add/remove which take WarpMarker
        objects, `Clip.move_warp_marker` has the signature
        `(marker_beat_time: float, beat_time_distance: float)` — pass
        the existing marker's current beat_time + a DELTA (not new abs).
        """
        try:
            clip = self._get_clip_at(track_index, clip_index)
            if not clip.is_audio_clip:
                raise ValueError("warp markers require audio clip")
            if not hasattr(clip, "move_warp_marker"):
                raise NotImplementedError("Clip.move_warp_marker not available")
            delta = float(new_beat_time) - float(beat_time)
            clip.move_warp_marker(float(beat_time), delta)
            return {
                "track_index": track_index,
                "clip_index": clip_index,
                "moved": True,
                "from_beat_time": float(beat_time),
                "to_beat_time": float(new_beat_time),
                "delta_beats": delta,
            }
        except Exception as e:
            self.log_message("Error moving warp marker: " + str(e))
            raise

    # ---------------- Clip details batch (2026-05-17) ----------------
    # color, gain, pitch, launch settings, follow actions

    _LAUNCH_MODE_NAMES = {0: "Trigger", 1: "Gate", 2: "Toggle", 3: "Repeat"}
    _FOLLOW_ACTIONS = {
        0: "No Action", 1: "Stop", 2: "Play Again", 3: "Previous",
        4: "Next", 5: "First", 6: "Last", 7: "Any", 8: "Other",
    }
    # Launch quantization uses Song.Quantization enum:
    # 0=Global, 1=None, 2=8b, 3=4b, 4=2b, 5=1b, 6=1/2, 7=1/2T, 8=1/4, 9=1/4T,
    # 10=1/8, 11=1/8T, 12=1/16, 13=1/16T, 14=1/32
    _LAUNCH_QUANT_NAMES = {
        0: "Global", 1: "None", 2: "8 Bars", 3: "4 Bars", 4: "2 Bars",
        5: "1 Bar", 6: "1/2", 7: "1/2T", 8: "1/4", 9: "1/4T",
        10: "1/8", 11: "1/8T", 12: "1/16", 13: "1/16T", 14: "1/32",
    }
    _LAUNCH_QUANT_FROM_STR = {v.lower(): k for k, v in _LAUNCH_QUANT_NAMES.items()}

    def _resolve_launch_mode(self, mode):
        if isinstance(mode, (int, float)):
            v = int(mode)
            if v not in self._LAUNCH_MODE_NAMES:
                raise ValueError("launch_mode int must be 0..3")
            return v
        key = str(mode).strip().lower()
        for k, name in self._LAUNCH_MODE_NAMES.items():
            if name.lower() == key:
                return k
        raise ValueError("launch_mode must be one of {0} (got '{1}')".format(
            list(self._LAUNCH_MODE_NAMES.values()), mode))

    def _resolve_launch_quant(self, q):
        if isinstance(q, (int, float)):
            v = int(q)
            if v not in self._LAUNCH_QUANT_NAMES:
                raise ValueError("launch_quantization int must be 0..14")
            return v
        key = str(q).strip().lower()
        if key in self._LAUNCH_QUANT_FROM_STR:
            return self._LAUNCH_QUANT_FROM_STR[key]
        raise ValueError("Unknown launch_quantization '{0}'. Valid: {1}".format(
            q, list(self._LAUNCH_QUANT_NAMES.values())))

    def _resolve_follow_action(self, action):
        if isinstance(action, (int, float)):
            v = int(action)
            if v not in self._FOLLOW_ACTIONS:
                raise ValueError("follow_action int must be 0..8")
            return v
        key = str(action).strip().lower()
        for k, name in self._FOLLOW_ACTIONS.items():
            if name.lower() == key:
                return k
        raise ValueError("follow_action must be one of {0} (got '{1}')".format(
            list(self._FOLLOW_ACTIONS.values()), action))

    def _get_clip_settings(self, track_index, clip_index):
        """Read a clip's full settings: color, gain (audio), pitch (audio),
        launch mode/quantization/legato/looping, follow action (Live 11+).
        """
        try:
            clip = self._get_clip_at(track_index, clip_index)
            is_audio = bool(clip.is_audio_clip)
            out = {
                "track_index": track_index,
                "clip_index": clip_index,
                "name": clip.name,
                "is_audio": is_audio,
                "length": float(clip.length),
                "color": int(clip.color) if hasattr(clip, "color") else None,
                "color_index": int(clip.color_index) if hasattr(clip, "color_index") else None,
                "looping": bool(clip.looping) if hasattr(clip, "looping") else None,
            }
            # Launch settings (all clip types)
            for attr in ("launch_mode", "launch_quantization", "legato"):
                if hasattr(clip, attr):
                    v = getattr(clip, attr)
                    out[attr] = bool(v) if attr == "legato" else int(v)
            if "launch_mode" in out:
                out["launch_mode_name"] = self._LAUNCH_MODE_NAMES.get(out["launch_mode"])
            if "launch_quantization" in out:
                out["launch_quantization_name"] = self._LAUNCH_QUANT_NAMES.get(out["launch_quantization"])
            # Follow action (Live 11+)
            for attr in ("follow_action_enabled", "follow_action_a", "follow_action_b",
                         "follow_action_chance_a", "follow_action_chance_b",
                         "follow_action_time"):
                if hasattr(clip, attr):
                    v = getattr(clip, attr)
                    out[attr] = bool(v) if attr == "follow_action_enabled" else (
                        float(v) if attr == "follow_action_time" else int(v))
            if "follow_action_a" in out:
                out["follow_action_a_name"] = self._FOLLOW_ACTIONS.get(out["follow_action_a"])
            if "follow_action_b" in out:
                out["follow_action_b_name"] = self._FOLLOW_ACTIONS.get(out["follow_action_b"])
            # Audio-clip extras
            if is_audio:
                for attr in ("gain", "pitch_coarse", "pitch_fine"):
                    if hasattr(clip, attr):
                        out[attr] = float(getattr(clip, attr))
            return out
        except Exception as e:
            self.log_message("Error reading clip settings: " + str(e))
            raise

    def _set_clip_color(self, track_index, clip_index, color=None, color_index=None):
        try:
            clip = self._get_clip_at(track_index, clip_index)
            changed = {}
            if color is not None and hasattr(clip, "color"):
                clip.color = int(color)
                changed["color"] = int(clip.color)
            if color_index is not None and hasattr(clip, "color_index"):
                clip.color_index = int(color_index)
                changed["color_index"] = int(clip.color_index)
            if not changed:
                raise ValueError("Provide color (RGB int) or color_index (0..69)")
            return {"track_index": track_index, "clip_index": clip_index,
                    "name": clip.name, "changed": changed}
        except Exception as e:
            self.log_message("Error setting clip color: " + str(e))
            raise

    def _set_clip_gain(self, track_index, clip_index, gain):
        """Audio clip only. Gain is normalized 0..1 (Live's internal scale)."""
        try:
            clip = self._get_clip_at(track_index, clip_index)
            if not clip.is_audio_clip:
                raise ValueError("set_clip_gain requires audio clip, got MIDI")
            if not hasattr(clip, "gain"):
                raise NotImplementedError("Clip.gain not available on this Live version")
            v = max(0.0, min(1.0, float(gain)))
            clip.gain = v
            return {"track_index": track_index, "clip_index": clip_index,
                    "name": clip.name, "gain": float(clip.gain)}
        except Exception as e:
            self.log_message("Error setting clip gain: " + str(e))
            raise

    def _set_clip_pitch(self, track_index, clip_index, coarse=None, fine=None):
        """Audio clip only. coarse: -48..+48 semitones, fine: -50..+50 cents."""
        try:
            clip = self._get_clip_at(track_index, clip_index)
            if not clip.is_audio_clip:
                raise ValueError("set_clip_pitch requires audio clip, got MIDI")
            changed = {}
            if coarse is not None and hasattr(clip, "pitch_coarse"):
                c = max(-48, min(48, int(coarse)))
                clip.pitch_coarse = c
                changed["pitch_coarse"] = int(clip.pitch_coarse)
            if fine is not None and hasattr(clip, "pitch_fine"):
                f = max(-50, min(50, int(fine)))
                clip.pitch_fine = f
                changed["pitch_fine"] = int(clip.pitch_fine)
            if not changed:
                raise ValueError("Provide coarse (semitones) and/or fine (cents)")
            return {"track_index": track_index, "clip_index": clip_index,
                    "name": clip.name, "changed": changed}
        except Exception as e:
            self.log_message("Error setting clip pitch: " + str(e))
            raise

    def _set_clip_launch_settings(self, track_index, clip_index, launch_mode=None,
                                   launch_quantization=None, legato=None, looping=None):
        try:
            clip = self._get_clip_at(track_index, clip_index)
            changed = {}
            if launch_mode is not None and hasattr(clip, "launch_mode"):
                v = self._resolve_launch_mode(launch_mode)
                clip.launch_mode = v
                changed["launch_mode"] = int(clip.launch_mode)
                changed["launch_mode_name"] = self._LAUNCH_MODE_NAMES.get(int(clip.launch_mode))
            if launch_quantization is not None and hasattr(clip, "launch_quantization"):
                v = self._resolve_launch_quant(launch_quantization)
                clip.launch_quantization = v
                changed["launch_quantization"] = int(clip.launch_quantization)
                changed["launch_quantization_name"] = self._LAUNCH_QUANT_NAMES.get(int(clip.launch_quantization))
            if legato is not None and hasattr(clip, "legato"):
                clip.legato = bool(legato)
                changed["legato"] = bool(clip.legato)
            if looping is not None and hasattr(clip, "looping"):
                clip.looping = bool(looping)
                changed["looping"] = bool(clip.looping)
            if not changed:
                raise ValueError("Provide at least one of launch_mode/launch_quantization/legato/looping")
            return {"track_index": track_index, "clip_index": clip_index,
                    "name": clip.name, "changed": changed}
        except Exception as e:
            self.log_message("Error setting clip launch settings: " + str(e))
            raise

    def _set_clip_follow_action(self, track_index, clip_index,
                                  enabled=None, action_a=None, action_b=None,
                                  chance_a=None, chance_b=None, time_beats=None):
        """Set follow action on a clip.

        LIVE API LIMITATION (Live 12.3.7, verified 2026-05-17): follow
        action properties are NOT exposed on Clip in the LOM. Grep of
        the entire AbletonLive12_MIDIRemoteScripts directory returns zero
        references to `follow_action`. Despite being a Live 11+
        user-facing feature, the LOM doesn't surface it. Tool raises
        NotImplementedError with guidance.
        """
        try:
            clip = self._get_clip_at(track_index, clip_index)
            if not hasattr(clip, "follow_action_enabled"):
                raise NotImplementedError(
                    "Clip.follow_action_* not exposed on Live 12.3.7 LOM "
                    "(verified — no Remote Script references the API). "
                    "Configure follow actions manually in Live's clip view.")
            changed = {}
            if enabled is not None:
                clip.follow_action_enabled = bool(enabled)
                changed["follow_action_enabled"] = bool(clip.follow_action_enabled)
            if action_a is not None:
                v = self._resolve_follow_action(action_a)
                clip.follow_action_a = v
                changed["follow_action_a"] = int(clip.follow_action_a)
                changed["follow_action_a_name"] = self._FOLLOW_ACTIONS.get(int(clip.follow_action_a))
            if action_b is not None:
                v = self._resolve_follow_action(action_b)
                clip.follow_action_b = v
                changed["follow_action_b"] = int(clip.follow_action_b)
                changed["follow_action_b_name"] = self._FOLLOW_ACTIONS.get(int(clip.follow_action_b))
            if chance_a is not None:
                clip.follow_action_chance_a = max(0, min(127, int(chance_a)))
                changed["follow_action_chance_a"] = int(clip.follow_action_chance_a)
            if chance_b is not None:
                clip.follow_action_chance_b = max(0, min(127, int(chance_b)))
                changed["follow_action_chance_b"] = int(clip.follow_action_chance_b)
            if time_beats is not None:
                clip.follow_action_time = max(0.0, float(time_beats))
                changed["follow_action_time"] = float(clip.follow_action_time)
            if not changed:
                raise ValueError("No follow-action fields provided")
            return {"track_index": track_index, "clip_index": clip_index,
                    "name": clip.name, "changed": changed}
        except Exception as e:
            self.log_message("Error setting clip follow action: " + str(e))
            raise

    # ---------------- Track-state extras (2026-05-17) ----------------

    _MONITORING_MODES = {"in": 0, "auto": 1, "off": 2}
    _MONITORING_NAMES = {0: "in", 1: "auto", 2: "off"}

    def _resolve_track(self, track_index, allow_master=False, allow_return=False):
        """Resolve a track index to a Track object, supporting negative
        indices for master/return when allowed."""
        if track_index >= 0 and track_index < len(self._song.tracks):
            return self._song.tracks[track_index]
        raise IndexError("Track index {0} out of range".format(track_index))

    def _set_track_monitoring(self, track_index, mode):
        """Set Track.current_monitoring_state.

        mode: 'in' (always monitor), 'auto' (default — only when armed/playing),
              'off' (never monitor). Or int 0/1/2.
        """
        try:
            track = self._resolve_track(track_index)
            if isinstance(mode, (int, float)):
                v = int(mode)
                if v not in (0, 1, 2):
                    raise ValueError("monitoring mode int must be 0/1/2")
            else:
                key = str(mode).lower().strip()
                if key not in self._MONITORING_MODES:
                    raise ValueError("mode must be 'in'/'auto'/'off' (got '{0}')".format(mode))
                v = self._MONITORING_MODES[key]
            if not hasattr(track, "current_monitoring_state"):
                raise NotImplementedError(
                    "Track '{0}' has no monitoring (not an audio/midi input track)".format(track.name))
            track.current_monitoring_state = v
            actual = int(track.current_monitoring_state)
            return {
                "track_index": track_index,
                "name": track.name,
                "monitoring": self._MONITORING_NAMES.get(actual, "unknown"),
                "monitoring_int": actual,
            }
        except Exception as e:
            self.log_message("Error setting track monitoring: " + str(e))
            raise

    def _set_track_freeze(self, track_index, freeze):
        """Freeze or unfreeze a track.

        LIVE API LIMITATION (Live 12.3.7, verified 2026-05-17):
        `Track.freeze()` / `Track.unfreeze()` methods are NOT exposed
        on the LOM. Only the read-only `Track.is_frozen` property exists.
        Push2 + all Remote Scripts only read this state — freezing must
        be done via Live's UI (right-click track → Freeze Track).

        The Live 11 API docs claim freeze() exists, but it's gated to
        internal use only. Raises NotImplementedError with guidance.
        """
        track = self._resolve_track(track_index)
        is_frozen = bool(getattr(track, "is_frozen", False))
        raise NotImplementedError(
            ("Track.freeze()/unfreeze() not exposed on Live 12.3.7 LOM. "
             "Track '{0}' currently is_frozen={1}. "
             "To toggle: right-click the track in Live and choose "
             "Freeze Track / Unfreeze Track.").format(track.name, is_frozen))

    def _set_track_color(self, track_index, color=None, color_index=None):
        """Set track color via RGB int or Live's color palette index (0..69).

        Pass either `color` (RGB) or `color_index` (palette). Or both.
        """
        try:
            track = self._resolve_track(track_index)
            changed = {}
            if color is not None and hasattr(track, "color"):
                track.color = int(color)
                changed["color"] = int(track.color)
            if color_index is not None and hasattr(track, "color_index"):
                track.color_index = int(color_index)
                changed["color_index"] = int(track.color_index)
            if not changed:
                raise ValueError("Provide color (RGB int) or color_index (0..69)")
            return {
                "track_index": track_index,
                "name": track.name,
                "changed": changed,
            }
        except Exception as e:
            self.log_message("Error setting track color: " + str(e))
            raise

    def _set_track_fold(self, track_index, fold_state):
        """Collapse / expand a group track (Track.fold_state).

        Only works on foldable tracks (group tracks). Errors otherwise.
        """
        try:
            track = self._resolve_track(track_index)
            if not bool(getattr(track, "is_foldable", False)):
                raise NotImplementedError(
                    "Track '{0}' is not foldable (not a group track)".format(track.name))
            track.fold_state = bool(fold_state)
            return {
                "track_index": track_index,
                "name": track.name,
                "fold_state": bool(track.fold_state),
                "is_foldable": True,
            }
        except Exception as e:
            self.log_message("Error setting track fold: " + str(e))
            raise

    def _summarize_routing_type(self, rt):
        """Pull a few common fields off a Live RoutingType object."""
        out = {}
        for attr in ("display_name", "category", "attached_object"):
            try:
                v = getattr(rt, attr, None)
                if attr == "attached_object" and v is not None:
                    out[attr] = getattr(v, "name", str(v))
                elif v is not None:
                    out[attr] = v
            except Exception:
                pass
        return out

    def _get_available_routings(self, track_index):
        """List Track.available_input/output_routing_types + channels.

        Closes the discovery gap before calling set_track_routing — you
        need to know what's available to route to.
        """
        try:
            track = self._resolve_track(track_index)
            def safe_list(attr):
                items = getattr(track, attr, None)
                if items is None:
                    return None
                try:
                    return [self._summarize_routing_type(rt) for rt in items]
                except Exception as e:
                    return {"_error": str(e)}
            return {
                "track_index": track_index,
                "name": track.name,
                "available_input_routing_types": safe_list("available_input_routing_types"),
                "available_input_routing_channels": safe_list("available_input_routing_channels"),
                "available_output_routing_types": safe_list("available_output_routing_types"),
                "available_output_routing_channels": safe_list("available_output_routing_channels"),
                "current_input_routing_type": self._summarize_routing_type(
                    getattr(track, "input_routing_type", None)) if hasattr(track, "input_routing_type") else None,
                "current_output_routing_type": self._summarize_routing_type(
                    getattr(track, "output_routing_type", None)) if hasattr(track, "output_routing_type") else None,
            }
        except Exception as e:
            self.log_message("Error getting available routings: " + str(e))
            raise

    # ---------------- Scenes batch (2026-05-17) ----------------

    def _summarize_scene(self, scene, index):
        out = {
            "index": index,
            "name": scene.name,
            "is_triggered": bool(getattr(scene, "is_triggered", False)),
            "is_empty": bool(getattr(scene, "is_empty", False)),
        }
        for attr in ("color", "color_index", "tempo",
                     "time_signature_numerator", "time_signature_denominator"):
            try:
                if hasattr(scene, attr):
                    out[attr] = getattr(scene, attr)
            except Exception:
                pass
        return out

    def _get_scenes(self):
        """List all scenes with their metadata."""
        try:
            scenes = list(self._song.scenes)
            return {
                "count": len(scenes),
                "scenes": [self._summarize_scene(s, i) for i, s in enumerate(scenes)],
            }
        except Exception as e:
            self.log_message("Error reading scenes: " + str(e))
            raise

    def _create_scene(self, index=-1):
        """Create a new scene at the given 0-based index. -1 = at the end.
        Returns the new scene's index + name.
        """
        try:
            song = self._song
            n = len(song.scenes)
            if index is None or int(index) < 0:
                idx = n  # append at end
            else:
                idx = int(index)
                if idx > n:
                    raise IndexError("Cannot create scene at index {0} (only {1} scenes)".format(idx, n))
            song.create_scene(idx)
            new_scenes = list(song.scenes)
            new_scene = new_scenes[idx]
            return {
                "created": True,
                "scene_index": idx,
                "name": new_scene.name,
                "total_scenes": len(new_scenes),
            }
        except Exception as e:
            self.log_message("Error creating scene: " + str(e))
            raise

    def _delete_scene(self, scene_index):
        """Delete a scene by index."""
        try:
            song = self._song
            scenes = list(song.scenes)
            if scene_index < 0 or scene_index >= len(scenes):
                raise IndexError("scene_index {0} out of range (have {1})".format(
                    scene_index, len(scenes)))
            deleted_name = scenes[scene_index].name
            song.delete_scene(scene_index)
            return {
                "deleted": True,
                "scene_index": scene_index,
                "deleted_name": deleted_name,
                "total_scenes": len(song.scenes),
            }
        except Exception as e:
            self.log_message("Error deleting scene: " + str(e))
            raise

    def _duplicate_scene(self, scene_index):
        """Duplicate a scene at the given index. New scene appears right after."""
        try:
            song = self._song
            scenes = list(song.scenes)
            if scene_index < 0 or scene_index >= len(scenes):
                raise IndexError("scene_index {0} out of range (have {1})".format(
                    scene_index, len(scenes)))
            song.duplicate_scene(scene_index)
            new_scenes = list(song.scenes)
            new_idx = scene_index + 1
            return {
                "duplicated": True,
                "source_index": scene_index,
                "new_index": new_idx,
                "new_name": new_scenes[new_idx].name if new_idx < len(new_scenes) else None,
                "total_scenes": len(new_scenes),
            }
        except Exception as e:
            self.log_message("Error duplicating scene: " + str(e))
            raise

    def _capture_and_insert_scene(self):
        """Capture currently-playing clips into a new scene (Song.capture_and_insert_scene).
        Inserts the new scene after the currently-selected scene."""
        try:
            song = self._song
            before = len(song.scenes)
            song.capture_and_insert_scene()
            after = len(song.scenes)
            if after <= before:
                return {"captured": False, "reason": "no new scene created (no playing clips?)"}
            # Find the new scene by id-diff
            return {
                "captured": True,
                "total_scenes": after,
                "new_scenes_count": after - before,
            }
        except Exception as e:
            self.log_message("Error capture_and_insert_scene: " + str(e))
            raise

    def _set_scene_props(self, scene_index, name=None, color=None, color_index=None,
                          tempo=None, signature_numerator=None,
                          signature_denominator=None):
        """Set scene properties. All fields optional; pass only what to change.

        - name: scene name (str)
        - color: full RGB int (0xRRGGBB)
        - color_index: 0..69 from Live's color palette
        - tempo: float; pass -1.0 to clear tempo override
        - signature_numerator / signature_denominator: time signature override
        """
        try:
            scenes = list(self._song.scenes)
            if scene_index < 0 or scene_index >= len(scenes):
                raise IndexError("scene_index out of range")
            scene = scenes[scene_index]
            changed = {}
            if name is not None:
                scene.name = str(name)
                changed["name"] = scene.name
            if color is not None and hasattr(scene, "color"):
                scene.color = int(color)
                changed["color"] = int(scene.color)
            if color_index is not None and hasattr(scene, "color_index"):
                scene.color_index = int(color_index)
                changed["color_index"] = int(scene.color_index)
            if tempo is not None and hasattr(scene, "tempo"):
                scene.tempo = float(tempo)
                changed["tempo"] = float(scene.tempo)
            if signature_numerator is not None and hasattr(scene, "time_signature_numerator"):
                scene.time_signature_numerator = int(signature_numerator)
                changed["time_signature_numerator"] = int(scene.time_signature_numerator)
            if signature_denominator is not None and hasattr(scene, "time_signature_denominator"):
                scene.time_signature_denominator = int(signature_denominator)
                changed["time_signature_denominator"] = int(scene.time_signature_denominator)
            if not changed:
                raise ValueError("No fields provided to change")
            return {
                "scene_index": scene_index,
                "changed": changed,
                "scene": self._summarize_scene(scene, scene_index),
            }
        except Exception as e:
            self.log_message("Error setting scene props: " + str(e))
            raise

    def _fire_scene(self, scene_index):
        """Fire (trigger) a scene — launches all its clips."""
        try:
            scenes = list(self._song.scenes)
            if scene_index < 0 or scene_index >= len(scenes):
                raise IndexError("scene_index out of range")
            scene = scenes[scene_index]
            scene.fire()
            return {
                "fired": True,
                "scene_index": scene_index,
                "name": scene.name,
            }
        except Exception as e:
            self.log_message("Error firing scene: " + str(e))
            raise

    # ---------------- Transport batch (2026-05-17) ----------------
    # Song-level state: metronome, count-in, quantization, time signature,
    # session-record state, punch region, tap/nudge tempo.

    def _safe_get(self, obj, attr, cast=None):
        """getattr that surfaces C++-binding errors per field rather than
        failing the whole transport-state read. Returns dict with 'value' or 'error'."""
        try:
            v = getattr(obj, attr)
            if cast is not None:
                v = cast(v)
            return v
        except Exception as e:
            return {"_error": str(e)}

    def _get_transport_state(self):
        """Read song-level transport state in one call.

        Each field wrapped individually so a single Live API quirk
        doesn't kill the whole response.
        """
        try:
            song = self._song
            return {
                "tempo": song.tempo,
                "is_playing": self._safe_get(song, "is_playing", bool),
                "metronome": self._safe_get(song, "metronome", bool),
                "count_in_duration": self._safe_get(song, "count_in_duration"),
                "midi_recording_quantization": self._safe_get(song, "midi_recording_quantization"),
                "clip_trigger_quantization": self._safe_get(song, "clip_trigger_quantization"),
                "swing_amount": self._safe_get(song, "swing_amount"),
                "signature_numerator": song.signature_numerator,
                "signature_denominator": song.signature_denominator,
                "session_record": self._safe_get(song, "session_record", bool),
                "arrangement_overdub": self._safe_get(song, "arrangement_overdub", bool),
                "back_to_arranger": self._safe_get(song, "back_to_arranger", bool),
                "punch_in": self._safe_get(song, "punch_in", bool),
                "punch_out": self._safe_get(song, "punch_out", bool),
                "loop": self._safe_get(song, "loop", bool),
                "loop_start": self._safe_get(song, "loop_start"),
                "loop_length": self._safe_get(song, "loop_length"),
                "song_length": self._safe_get(song, "song_length"),
                "groove_amount": self._safe_get(song, "groove_amount"),
            }
        except Exception as e:
            self.log_message("Error reading transport state: " + str(e))
            raise

    def _set_metronome(self, enabled):
        """Toggle Live's metronome (Song.metronome)."""
        try:
            self._song.metronome = bool(enabled)
            return {"metronome": bool(self._song.metronome)}
        except Exception as e:
            self.log_message("Error setting metronome: " + str(e))
            raise

    def _set_count_in(self, bars):
        """Set count-in duration.

        LIVE API LIMITATION (Live 12.3.7, verified 2026-05-17):
        `Song.count_in_duration` is read-only — the property has no setter.
        Push2's `transport_state.py` only reads this property; setting is
        UI-only. Tool raises NotImplementedError with guidance.
        """
        raise NotImplementedError(
            "Song.count_in_duration is read-only in Live 12.3.7. "
            "Change manually via Live's Preferences > Record/Warp/Launch "
            "> Count-in, or the count-in dropdown in the transport bar.")

    def _set_record_quantization(self, midi_quant=None, trigger_quant=None, swing=None):
        """Update one or more record/trigger quantization settings.

        - midi_quant / trigger_quant: int enum or string grid name
          (same as quantize_clip_notes — '1/4', '1/8', '1/16', '1/16t', 'none', etc.)
        - swing: 0.0..1.0 swing amount applied to recordings
        """
        try:
            song = self._song
            changed = {}
            if midi_quant is not None:
                v = self._resolve_quantize_grid(midi_quant)
                song.midi_recording_quantization = v
                changed["midi_recording_quantization"] = int(song.midi_recording_quantization)
            if trigger_quant is not None:
                v = self._resolve_quantize_grid(trigger_quant)
                song.clip_trigger_quantization = v
                changed["clip_trigger_quantization"] = int(song.clip_trigger_quantization)
            if swing is not None:
                v = max(0.0, min(1.0, float(swing)))
                song.swing_amount = v
                changed["swing_amount"] = float(song.swing_amount)
            if not changed:
                raise ValueError("No fields provided (midi_quant/trigger_quant/swing)")
            return {"changed": changed}
        except Exception as e:
            self.log_message("Error setting record quantization: " + str(e))
            raise

    _VALID_DENOMINATORS = (1, 2, 4, 8, 16)

    def _set_time_signature(self, numerator, denominator):
        """Set Song.signature_numerator and signature_denominator."""
        try:
            n = int(numerator)
            d = int(denominator)
            if n < 1 or n > 99:
                raise ValueError("numerator must be 1..99 (got {0})".format(n))
            if d not in self._VALID_DENOMINATORS:
                raise ValueError("denominator must be one of {0} (got {1})".format(
                    self._VALID_DENOMINATORS, d))
            self._song.signature_numerator = n
            self._song.signature_denominator = d
            return {
                "signature_numerator": int(self._song.signature_numerator),
                "signature_denominator": int(self._song.signature_denominator),
            }
        except Exception as e:
            self.log_message("Error setting time signature: " + str(e))
            raise

    def _set_session_record(self, session_record=None, arrangement_overdub=None,
                            back_to_arranger=None):
        """Toggle session/arrangement record state.

        - session_record: arms the global session-record overdub
        - arrangement_overdub: enables arrangement-view overdub on playback
        - back_to_arranger: jumps arrangement playhead back to arranger position
        """
        try:
            song = self._song
            changed = {}
            if session_record is not None:
                song.session_record = bool(session_record)
                changed["session_record"] = bool(song.session_record)
            if arrangement_overdub is not None:
                song.arrangement_overdub = bool(arrangement_overdub)
                changed["arrangement_overdub"] = bool(song.arrangement_overdub)
            if back_to_arranger is not None:
                song.back_to_arranger = bool(back_to_arranger)
                changed["back_to_arranger"] = bool(song.back_to_arranger)
            if not changed:
                raise ValueError(
                    "No fields provided (session_record/arrangement_overdub/back_to_arranger)")
            return {"changed": changed}
        except Exception as e:
            self.log_message("Error setting session record: " + str(e))
            raise

    def _set_punch_region(self, punch_in=None, punch_out=None):
        """Toggle Song.punch_in and Song.punch_out.

        These work with the arrangement loop region to mark a punch zone
        for arrangement recording.

        NOTE (Live 12.3.7): punch_in/punch_out writes are silently dropped
        unless `Song.loop = True` (the arrangement loop button is engaged).
        We surface a warning when this happens.
        """
        try:
            song = self._song
            loop_enabled = bool(getattr(song, "loop", False))
            changed = {}
            warning = None
            if punch_in is not None:
                song.punch_in = bool(punch_in)
                actual = bool(song.punch_in)
                changed["punch_in"] = actual
                if actual != bool(punch_in):
                    warning = ("punch write didn't stick — "
                               "Song.loop = {0}; enable the arrangement loop first").format(loop_enabled)
            if punch_out is not None:
                song.punch_out = bool(punch_out)
                actual = bool(song.punch_out)
                changed["punch_out"] = actual
                if actual != bool(punch_out) and warning is None:
                    warning = ("punch write didn't stick — "
                               "Song.loop = {0}; enable the arrangement loop first").format(loop_enabled)
            if not changed:
                raise ValueError("No fields provided (punch_in/punch_out)")
            result = {"changed": changed, "loop_enabled": loop_enabled}
            if warning:
                result["warning"] = warning
            return result
        except Exception as e:
            self.log_message("Error setting punch region: " + str(e))
            raise

    def _tap_tempo(self):
        """Live's tap_tempo() — sends a single tap event. Call repeatedly
        on beat to set tempo from taps."""
        try:
            before = float(self._song.tempo)
            self._song.tap_tempo()
            return {
                "tempo_before": before,
                "tempo_after": float(self._song.tempo),
            }
        except Exception as e:
            self.log_message("Error tap_tempo: " + str(e))
            raise

    def _bump_tempo(self, delta_bpm):
        """Adjust Song.tempo by a fixed BPM delta (permanent change).

        NOTE 2026-05-17: This is NOT `Song.nudge_up`/`nudge_down` — those
        are Live's DJ-style temporary pitch-sync nudges (active only while
        a button is held; tempo returns on release). For a permanent
        tempo bump (like clicking the ◀/▶ arrows in Live's transport bar),
        write `Song.tempo` directly. Range: 20-999 BPM (Live's limits).
        """
        try:
            d = float(delta_bpm)
            before = float(self._song.tempo)
            new_tempo = max(20.0, min(999.0, before + d))
            self._song.tempo = new_tempo
            return {
                "delta_bpm": d,
                "tempo_before": before,
                "tempo_after": float(self._song.tempo),
                "clamped": new_tempo != (before + d),
            }
        except Exception as e:
            self.log_message("Error bump_tempo: " + str(e))
            raise

    def _set_selection(self, kind, index=None, scene_index=None, return_index=None,
                       clip_index=None):
        """Set what's selected in the view.

        kind:
          - 'track': index = track index (0-based)
          - 'return': return_index = 0..N-1
          - 'master': selects master track
          - 'scene': scene_index
          - 'clip': index = track_index, clip_index = clip slot index
                    (sets detail_clip + highlighted_clip_slot)
        """
        try:
            view = self._song.view
            k = kind.lower()
            if k == "track":
                if index is None:
                    raise ValueError("index required for kind='track'")
                view.selected_track = self._song.tracks[int(index)]
                return {"selected": "track", "index": int(index),
                        "name": self._song.tracks[int(index)].name}
            elif k == "return":
                if return_index is None:
                    raise ValueError("return_index required for kind='return'")
                view.selected_track = self._song.return_tracks[int(return_index)]
                return {"selected": "return", "index": int(return_index),
                        "name": self._song.return_tracks[int(return_index)].name}
            elif k == "master":
                view.selected_track = self._song.master_track
                return {"selected": "master"}
            elif k == "scene":
                if scene_index is None:
                    raise ValueError("scene_index required for kind='scene'")
                view.selected_scene = self._song.scenes[int(scene_index)]
                return {"selected": "scene", "index": int(scene_index),
                        "name": self._song.scenes[int(scene_index)].name}
            elif k == "clip":
                if index is None or clip_index is None:
                    raise ValueError("index and clip_index required for kind='clip'")
                track = self._song.tracks[int(index)]
                slot = track.clip_slots[int(clip_index)]
                view.highlighted_clip_slot = slot
                if slot.has_clip:
                    view.detail_clip = slot.clip
                return {"selected": "clip", "track_index": int(index),
                        "clip_index": int(clip_index),
                        "has_clip": bool(slot.has_clip),
                        "clip_name": slot.clip.name if slot.has_clip else None}
            else:
                raise ValueError("Unknown kind '{0}'. Use track/return/master/scene/clip".format(kind))
        except Exception as e:
            self.log_message("Error setting selection: " + str(e))
            raise
