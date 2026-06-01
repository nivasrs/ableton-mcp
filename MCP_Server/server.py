# ableton_mcp_server.py
from mcp.server.fastmcp import FastMCP, Context
import socket
import json
import logging
from dataclasses import dataclass
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Any, List, Union, Optional

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AbletonMCPServer")

@dataclass
class AbletonConnection:
    host: str
    port: int
    sock: socket.socket = None
    
    def connect(self) -> bool:
        """Connect to the Ableton Remote Script socket server"""
        if self.sock:
            return True
            
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            logger.info(f"Connected to Ableton at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Ableton: {str(e)}")
            self.sock = None
            return False
    
    def disconnect(self):
        """Disconnect from the Ableton Remote Script"""
        if self.sock:
            try:
                self.sock.close()
            except Exception as e:
                logger.error(f"Error disconnecting from Ableton: {str(e)}")
            finally:
                self.sock = None

    def receive_full_response(self, sock, buffer_size=8192):
        """Receive the complete response, potentially in multiple chunks"""
        chunks = []
        sock.settimeout(15.0)  # Increased timeout for operations that might take longer
        
        try:
            while True:
                try:
                    chunk = sock.recv(buffer_size)
                    if not chunk:
                        if not chunks:
                            raise Exception("Connection closed before receiving any data")
                        break
                    
                    chunks.append(chunk)
                    
                    # Check if we've received a complete JSON object
                    try:
                        data = b''.join(chunks)
                        json.loads(data.decode('utf-8'))
                        logger.info(f"Received complete response ({len(data)} bytes)")
                        return data
                    except json.JSONDecodeError:
                        # Incomplete JSON, continue receiving
                        continue
                except socket.timeout:
                    logger.warning("Socket timeout during chunked receive")
                    break
                except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
                    logger.error(f"Socket connection error during receive: {str(e)}")
                    raise
        except Exception as e:
            logger.error(f"Error during receive: {str(e)}")
            raise
            
        # If we get here, we either timed out or broke out of the loop
        if chunks:
            data = b''.join(chunks)
            logger.info(f"Returning data after receive completion ({len(data)} bytes)")
            try:
                json.loads(data.decode('utf-8'))
                return data
            except json.JSONDecodeError:
                raise Exception("Incomplete JSON response received")
        else:
            raise Exception("No data received")

    def send_command(self, command_type: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Send a command to Ableton and return the response"""
        if not self.sock and not self.connect():
            raise ConnectionError("Not connected to Ableton")
        
        command = {
            "type": command_type,
            "params": params or {}
        }
        
        # Check if this is a state-modifying command
        is_modifying_command = command_type in [
            "create_midi_track", "create_audio_track", "set_track_name",
            "create_clip", "add_notes_to_clip", "set_clip_name",
            "set_tempo", "fire_clip", "stop_clip", "set_device_parameter",
            "start_playback", "stop_playback", "load_instrument_or_effect",
            "set_mixer_value", "set_arrangement_loop", "clear_clip_envelope",
            # Tier 1 writes
            "duplicate_track", "delete_track", "undo", "redo",
            "capture_midi", "stop_all_clips",
            # Tier 2 writes
            "delete_device", "move_device", "set_return_mixer_value",
            "set_track_routing", "set_track_state",
            # Tier 3 writes
            "delete_arrangement_clip", "set_clip_loop_region", "jump_to_beat",
            # Clip envelope writes
            "set_clip_envelope_point", "set_clip_envelope_curve",
            "re_enable_automation",
            # Rack chain / drum pad writes
            "set_chain_state", "set_chain_mixer_value", "set_drum_pad_state",
            # Master / return device parameter writes
            "set_master_device_parameter", "set_return_device_parameter",
            # Master / return chain mutations (2026-05-17)
            "load_master_item", "load_return_item", "create_return_track",
            # Live.Conversions wrappers (2026-05-17)
            "audio_to_midi_clip", "create_drum_rack_from_audio_clip",
            "create_midi_track_from_audio_clip",
            "move_track_devices_to_drum_pad", "convert_sliced_simpler_to_drum_rack",
            # High-value 6 writes (2026-05-17)
            "set_song_scale", "quantize_clip_notes",
            "set_or_delete_cue", "jump_to_cue", "delete_cue_by_index",
            "set_groove_params", "assign_groove_to_clip",
            "set_clip_warping", "set_warp_mode",
            "set_selection",
            # Transport batch (2026-05-17)
            "set_metronome", "set_count_in",
            "set_record_quantization", "set_time_signature",
            "set_session_record", "set_punch_region", "set_record_mode",
            "create_arrangement_clip_from_session",
            "set_arrangement_clip_position",
            "set_device_input_routing",
            "snap_clip_to_scale", "shape_clip_velocities", "set_cue_point_name",
            "tap_tempo", "bump_tempo",
            # Scenes batch (2026-05-17)
            "create_scene", "delete_scene", "duplicate_scene",
            "capture_and_insert_scene", "set_scene_props", "fire_scene",
            # Track-state extras (2026-05-17)
            "set_track_monitoring", "set_track_freeze",
            "set_track_color", "set_track_fold",
            # Clip details (2026-05-17)
            "set_clip_color", "set_clip_gain", "set_clip_pitch",
            "set_clip_launch_settings", "set_clip_follow_action",
            # Warp markers (2026-05-17)
            "add_warp_marker", "remove_warp_marker", "move_warp_marker",
            # Option-A batch (2026-06-01) — mutating commands only
            "duplicate_arrangement_clip",
            "begin_undo_step", "end_undo_step",
            "set_focused_view", "set_view_visible",
            "delete_notes_in_range", "delete_notes_with_pitch",
            "duplicate_clip_loop",
        ]
        
        try:
            logger.info(f"Sending command: {command_type} with params: {params}")
            
            # Send the command
            self.sock.sendall(json.dumps(command).encode('utf-8'))
            logger.info(f"Command sent, waiting for response...")
            
            # For state-modifying commands, add a small delay to give Ableton time to process
            if is_modifying_command:
                import time
                time.sleep(0.1)  # 100ms delay
            
            # Set timeout based on command type
            timeout = 15.0 if is_modifying_command else 10.0
            self.sock.settimeout(timeout)
            
            # Receive the response
            response_data = self.receive_full_response(self.sock)
            logger.info(f"Received {len(response_data)} bytes of data")
            
            # Parse the response
            response = json.loads(response_data.decode('utf-8'))
            logger.info(f"Response parsed, status: {response.get('status', 'unknown')}")
            
            if response.get("status") == "error":
                logger.error(f"Ableton error: {response.get('message')}")
                raise Exception(response.get("message", "Unknown error from Ableton"))
            
            # For state-modifying commands, add another small delay after receiving response
            if is_modifying_command:
                import time
                time.sleep(0.1)  # 100ms delay
            
            return response.get("result", {})
        except socket.timeout:
            logger.error("Socket timeout while waiting for response from Ableton")
            self.sock = None
            raise Exception("Timeout waiting for Ableton response")
        except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
            logger.error(f"Socket connection error: {str(e)}")
            self.sock = None
            raise Exception(f"Connection to Ableton lost: {str(e)}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON response from Ableton: {str(e)}")
            if 'response_data' in locals() and response_data:
                logger.error(f"Raw response (first 200 bytes): {response_data[:200]}")
            self.sock = None
            raise Exception(f"Invalid response from Ableton: {str(e)}")
        except Exception as e:
            logger.error(f"Error communicating with Ableton: {str(e)}")
            self.sock = None
            raise Exception(f"Communication error with Ableton: {str(e)}")

@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    """Manage server startup and shutdown lifecycle"""
    try:
        logger.info("AbletonMCP server starting up")
        
        try:
            ableton = get_ableton_connection()
            logger.info("Successfully connected to Ableton on startup")
        except Exception as e:
            logger.warning(f"Could not connect to Ableton on startup: {str(e)}")
            logger.warning("Make sure the Ableton Remote Script is running")
        
        yield {}
    finally:
        global _ableton_connection
        if _ableton_connection:
            logger.info("Disconnecting from Ableton on shutdown")
            _ableton_connection.disconnect()
            _ableton_connection = None
        logger.info("AbletonMCP server shut down")

# Create the MCP server with lifespan support
mcp = FastMCP(
    "AbletonMCP",
    lifespan=server_lifespan
)

# Global connection for resources
_ableton_connection = None

def get_ableton_connection():
    """Get or create a persistent Ableton connection"""
    global _ableton_connection
    
    if _ableton_connection is not None:
        try:
            # Test the connection with a simple ping
            # We'll try to send an empty message, which should fail if the connection is dead
            # but won't affect Ableton if it's alive
            _ableton_connection.sock.settimeout(1.0)
            _ableton_connection.sock.sendall(b'')
            return _ableton_connection
        except Exception as e:
            logger.warning(f"Existing connection is no longer valid: {str(e)}")
            try:
                _ableton_connection.disconnect()
            except:
                pass
            _ableton_connection = None
    
    # Connection doesn't exist or is invalid, create a new one
    if _ableton_connection is None:
        # Try to connect up to 3 times with a short delay between attempts
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                logger.info(f"Connecting to Ableton (attempt {attempt}/{max_attempts})...")
                _ableton_connection = AbletonConnection(host="localhost", port=9877)
                if _ableton_connection.connect():
                    logger.info("Created new persistent connection to Ableton")
                    
                    # Validate connection with a simple command
                    try:
                        # Get session info as a test
                        _ableton_connection.send_command("get_session_info")
                        logger.info("Connection validated successfully")
                        return _ableton_connection
                    except Exception as e:
                        logger.error(f"Connection validation failed: {str(e)}")
                        _ableton_connection.disconnect()
                        _ableton_connection = None
                        # Continue to next attempt
                else:
                    _ableton_connection = None
            except Exception as e:
                logger.error(f"Connection attempt {attempt} failed: {str(e)}")
                if _ableton_connection:
                    _ableton_connection.disconnect()
                    _ableton_connection = None
            
            # Wait before trying again, but only if we have more attempts left
            if attempt < max_attempts:
                import time
                time.sleep(1.0)
        
        # If we get here, all connection attempts failed
        if _ableton_connection is None:
            logger.error("Failed to connect to Ableton after multiple attempts")
            raise Exception("Could not connect to Ableton. Make sure the Remote Script is running.")
    
    return _ableton_connection


# Core Tool endpoints

@mcp.tool()
def get_session_info(ctx: Context) -> str:
    """Get detailed information about the current Ableton session"""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_session_info")
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting session info from Ableton: {str(e)}")
        return f"Error getting session info: {str(e)}"

@mcp.tool()
def get_track_info(ctx: Context, track_index: int) -> str:
    """
    Get detailed information about a specific track in Ableton.
    
    Parameters:
    - track_index: The index of the track to get information about
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_track_info", {"track_index": track_index})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting track info from Ableton: {str(e)}")
        return f"Error getting track info: {str(e)}"

@mcp.tool()
def create_midi_track(ctx: Context, index: int = -1) -> str:
    """
    Create a new MIDI track in the Ableton session.
    
    Parameters:
    - index: The index to insert the track at (-1 = end of list)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_midi_track", {"index": index})
        return f"Created new MIDI track: {result.get('name', 'unknown')}"
    except Exception as e:
        logger.error(f"Error creating MIDI track: {str(e)}")
        return f"Error creating MIDI track: {str(e)}"


@mcp.tool()
def set_track_name(ctx: Context, track_index: int, name: str) -> str:
    """
    Set the name of a track.
    
    Parameters:
    - track_index: The index of the track to rename
    - name: The new name for the track
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_name", {"track_index": track_index, "name": name})
        return f"Renamed track to: {result.get('name', name)}"
    except Exception as e:
        logger.error(f"Error setting track name: {str(e)}")
        return f"Error setting track name: {str(e)}"

@mcp.tool()
def create_clip(ctx: Context, track_index: int, clip_index: int, length: float = 4.0) -> str:
    """
    Create a new MIDI clip in the specified track and clip slot.
    
    Parameters:
    - track_index: The index of the track to create the clip in
    - clip_index: The index of the clip slot to create the clip in
    - length: The length of the clip in beats (default: 4.0)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_clip", {
            "track_index": track_index, 
            "clip_index": clip_index, 
            "length": length
        })
        return f"Created new clip at track {track_index}, slot {clip_index} with length {length} beats"
    except Exception as e:
        logger.error(f"Error creating clip: {str(e)}")
        return f"Error creating clip: {str(e)}"

@mcp.tool()
def add_notes_to_clip(
    ctx: Context, 
    track_index: int, 
    clip_index: int, 
    notes: List[Dict[str, Union[int, float, bool]]]
) -> str:
    """
    Add MIDI notes to a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - notes: List of note dictionaries, each with pitch, start_time, duration, velocity, and mute
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("add_notes_to_clip", {
            "track_index": track_index,
            "clip_index": clip_index,
            "notes": notes
        })
        return f"Added {len(notes)} notes to clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error adding notes to clip: {str(e)}")
        return f"Error adding notes to clip: {str(e)}"

@mcp.tool()
def set_clip_name(ctx: Context, track_index: int, clip_index: int, name: str) -> str:
    """
    Set the name of a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - name: The new name for the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_name", {
            "track_index": track_index,
            "clip_index": clip_index,
            "name": name
        })
        return f"Renamed clip at track {track_index}, slot {clip_index} to '{name}'"
    except Exception as e:
        logger.error(f"Error setting clip name: {str(e)}")
        return f"Error setting clip name: {str(e)}"

@mcp.tool()
def set_tempo(ctx: Context, tempo: float) -> str:
    """
    Set the tempo of the Ableton session.

    Parameters:
    - tempo: The new tempo in BPM
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_tempo", {"tempo": tempo})
        return f"Set tempo to {tempo} BPM"
    except Exception as e:
        logger.error(f"Error setting tempo: {str(e)}")
        return f"Error setting tempo: {str(e)}"


@mcp.tool()
def get_device_parameters(ctx: Context, track_index: int, device_index: int) -> str:
    """
    List all automatable parameters on a device.

    Parameters:
    - track_index: Index of the track containing the device
    - device_index: Index of the device on that track (as returned by get_track_info)

    Returns JSON list of {index, name, value, min, max, is_enabled}.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_device_parameters", {
            "track_index": track_index,
            "device_index": device_index,
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting device parameters: {str(e)}")
        return f"Error getting device parameters: {str(e)}"


@mcp.tool()
def get_device_parameter_value(
    ctx: Context,
    track_index: int,
    device_index: int,
    parameter: Union[int, str],
) -> str:
    """
    Read a single parameter's current value.

    Parameters:
    - track_index: Index of the track containing the device
    - device_index: Index of the device on that track
    - parameter: Either the parameter's integer index or its name (e.g. "Width")
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_device_parameter_value", {
            "track_index": track_index,
            "device_index": device_index,
            "parameter": parameter,
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting device parameter value: {str(e)}")
        return f"Error getting device parameter value: {str(e)}"


@mcp.tool()
def set_device_parameter(
    ctx: Context,
    track_index: int,
    device_index: int,
    parameter: Union[int, str],
    value: float,
) -> str:
    """
    Set a device parameter to a given value.

    Parameters:
    - track_index: Index of the track containing the device
    - device_index: Index of the device on that track
    - parameter: Parameter index (int) or name (str, e.g. "Width")
    - value: Target value; will be clamped to the parameter's [min, max] range
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_device_parameter", {
            "track_index": track_index,
            "device_index": device_index,
            "parameter": parameter,
            "value": value,
        })
        return (f"Set {result.get('name', parameter)} on track {track_index} "
                f"device {device_index} to {result.get('value', value)}")
    except Exception as e:
        logger.error(f"Error setting device parameter: {str(e)}")
        return f"Error setting device parameter: {str(e)}"


@mcp.tool()
def set_mixer_value(
    ctx: Context,
    track_index: int,
    param: str,
    value: float,
) -> str:
    """
    Set a mixer value on a track.

    Parameters:
    - track_index: Index of the track
    - param: One of "volume", "panning", or "send:N" where N is the send index (e.g. "send:0")
    - value: New value. Volume and sends are 0.0–1.0 (log-warped). Panning is -1.0 to +1.0.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_mixer_value", {
            "track_index": track_index,
            "param": param,
            "value": value,
        })
        return (f"Set {param} on track {track_index} to "
                f"{result.get('value', value)}")
    except Exception as e:
        logger.error(f"Error setting mixer value: {str(e)}")
        return f"Error setting mixer value: {str(e)}"


@mcp.tool()
def set_arrangement_loop(
    ctx: Context,
    start_beats: float,
    length_beats: float,
) -> str:
    """
    Set the arrangement loop region.

    Parameters:
    - start_beats: Loop start position in beats (>= 0)
    - length_beats: Loop length in beats (> 0)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_arrangement_loop", {
            "start_beats": start_beats,
            "length_beats": length_beats,
        })
        return (f"Loop set: start={result.get('loop_start', start_beats)} beats, "
                f"length={result.get('loop_length', length_beats)} beats")
    except Exception as e:
        logger.error(f"Error setting arrangement loop: {str(e)}")
        return f"Error setting arrangement loop: {str(e)}"


@mcp.tool()
def clear_clip_envelope(
    ctx: Context,
    track_index: int,
    clip_index: int,
    device_index: int = -1,
    parameter: Union[int, str, None] = None,
) -> str:
    """
    Clear automation envelope(s) from a session-view clip.

    Parameters:
    - track_index: Index of the track containing the clip
    - clip_index: Slot index of the clip
    - device_index: Device index on the track whose parameter to clear.
                    Ignored when parameter is None (clears all envelopes).
    - parameter: Parameter index or name. Omit (None) to clear all envelopes on the clip.
    """
    try:
        ableton = get_ableton_connection()
        payload = {
            "track_index": track_index,
            "clip_index": clip_index,
            "device_index": device_index,
            "parameter": parameter,
        }
        result = ableton.send_command("clear_clip_envelope", payload)
        if parameter is None:
            return (f"Cleared all envelopes on track {track_index}, "
                    f"clip {clip_index}")
        return (f"Cleared envelope for '{result.get('parameter', parameter)}' "
                f"on track {track_index}, clip {clip_index}")
    except Exception as e:
        logger.error(f"Error clearing clip envelope: {str(e)}")
        return f"Error clearing clip envelope: {str(e)}"


# ---------------------------------------------------------------------------
# Tier 1 — Missing basics
# ---------------------------------------------------------------------------

@mcp.tool()
def get_clip_notes(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Read the MIDI notes in a session-view clip.

    Parameters:
    - track_index: Index of the track containing the clip
    - clip_index: Slot index of the clip

    Returns JSON with note list: {pitch, start_time, duration, velocity, mute}.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_clip_notes", {
            "track_index": track_index,
            "clip_index": clip_index,
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting clip notes: {str(e)}")
        return f"Error getting clip notes: {str(e)}"


@mcp.tool()
def duplicate_track(ctx: Context, track_index: int) -> str:
    """
    Duplicate a track (including devices and session clips).

    Parameters:
    - track_index: Index of the track to duplicate
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("duplicate_track", {"track_index": track_index})
        return f"Duplicated track {track_index}; new track at index {result.get('new_index', '?')}"
    except Exception as e:
        logger.error(f"Error duplicating track: {str(e)}")
        return f"Error duplicating track: {str(e)}"


@mcp.tool()
def delete_track(ctx: Context, track_index: int) -> str:
    """
    Delete a track. DESTRUCTIVE — removes devices, clips, automation.

    Parameters:
    - track_index: Index of the track to delete
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("delete_track", {"track_index": track_index})
        return f"Deleted track {track_index} (was '{result.get('name', '?')}')"
    except Exception as e:
        logger.error(f"Error deleting track: {str(e)}")
        return f"Error deleting track: {str(e)}"


@mcp.tool()
def undo(ctx: Context) -> str:
    """Undo the last Live action. Returns the action name if successful."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("undo")
        if result.get("undone"):
            return f"Undid: {result.get('action', '(unknown)')}"
        return "Nothing to undo"
    except Exception as e:
        logger.error(f"Error during undo: {str(e)}")
        return f"Error during undo: {str(e)}"


@mcp.tool()
def redo(ctx: Context) -> str:
    """Redo the last undone action."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("redo")
        if result.get("redone"):
            return f"Redid: {result.get('action', '(unknown)')}"
        return "Nothing to redo"
    except Exception as e:
        logger.error(f"Error during redo: {str(e)}")
        return f"Error during redo: {str(e)}"


@mcp.tool()
def capture_midi(ctx: Context) -> str:
    """
    Capture recently-played MIDI into a new clip on the armed MIDI track.

    Requires at least one armed MIDI track with recent input.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("capture_midi")
        return f"Captured MIDI: {result.get('status', 'ok')}"
    except Exception as e:
        logger.error(f"Error capturing MIDI: {str(e)}")
        return f"Error capturing MIDI: {str(e)}"


@mcp.tool()
def stop_all_clips(ctx: Context) -> str:
    """Stop all session-view clips. Does NOT stop arrangement playback."""
    try:
        ableton = get_ableton_connection()
        ableton.send_command("stop_all_clips")
        return "Stopped all session clips"
    except Exception as e:
        logger.error(f"Error stopping all clips: {str(e)}")
        return f"Error stopping all clips: {str(e)}"


@mcp.tool()
def create_audio_track(ctx: Context, index: int = -1) -> str:
    """
    Create a new audio track.

    Parameters:
    - index: Insertion index (-1 = end of list)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_audio_track", {"index": index})
        return f"Created audio track: {result.get('name', 'unknown')} at index {result.get('index', '?')}"
    except Exception as e:
        logger.error(f"Error creating audio track: {str(e)}")
        return f"Error creating audio track: {str(e)}"


# ---------------------------------------------------------------------------
# Tier 2 — Devices, routing, state
# ---------------------------------------------------------------------------

@mcp.tool()
def delete_device(ctx: Context, track_index: int, device_index: int) -> str:
    """
    Delete a device from a track.

    Parameters:
    - track_index: Index of the track containing the device
    - device_index: Index of the device on that track
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("delete_device", {
            "track_index": track_index,
            "device_index": device_index,
        })
        return (f"Deleted device {device_index} (was '{result.get('name', '?')}') "
                f"from track {track_index}")
    except Exception as e:
        logger.error(f"Error deleting device: {str(e)}")
        return f"Error deleting device: {str(e)}"


@mcp.tool()
def move_device(ctx: Context, track_index: int, from_index: int, to_index: int) -> str:
    """
    Reorder a device within its track's chain.

    Parameters:
    - track_index: Index of the track
    - from_index: Current device index
    - to_index: Target device index

    Note: same-track reorder only; cross-track moves are not supported.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("move_device", {
            "track_index": track_index,
            "from_index": from_index,
            "to_index": to_index,
        })
        return (f"Moved device '{result.get('name', '?')}' "
                f"from {from_index} to {to_index} on track {track_index}")
    except Exception as e:
        logger.error(f"Error moving device: {str(e)}")
        return f"Error moving device: {str(e)}"


@mcp.tool()
def get_return_track_info(ctx: Context, return_index: int) -> str:
    """
    Get info for a return track (mixer state and devices).

    Parameters:
    - return_index: Index into song.return_tracks
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_return_track_info", {"return_index": return_index})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting return track info: {str(e)}")
        return f"Error getting return track info: {str(e)}"


@mcp.tool()
def set_return_mixer_value(ctx: Context, return_index: int, param: str, value: float) -> str:
    """
    Set a mixer value on a return track.

    Parameters:
    - return_index: Index into song.return_tracks
    - param: One of "volume", "panning", or "send:N"
    - value: New value (0.0–1.0 for volume/sends; -1.0 to +1.0 for panning)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_return_mixer_value", {
            "return_index": return_index,
            "param": param,
            "value": value,
        })
        return f"Set {param} on return {return_index} to {result.get('value', value)}"
    except Exception as e:
        logger.error(f"Error setting return mixer value: {str(e)}")
        return f"Error setting return mixer value: {str(e)}"


@mcp.tool()
def get_track_routing(ctx: Context, track_index: int) -> str:
    """
    Get input/output routing for a track, plus all available options.

    Parameters:
    - track_index: Index of the track
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_track_routing", {"track_index": track_index})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting track routing: {str(e)}")
        return f"Error getting track routing: {str(e)}"


@mcp.tool()
def set_track_routing(
    ctx: Context,
    track_index: int,
    direction: str,
    kind: str,
    display_name: str,
) -> str:
    """
    Set one routing field on a track.

    Parameters:
    - track_index: Index of the track
    - direction: "input" or "output"
    - kind: "type" or "channel"
    - display_name: Target option's display name (must match one listed by
                    get_track_routing under available_<direction>_<kind>s)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_routing", {
            "track_index": track_index,
            "direction": direction,
            "kind": kind,
            "display_name": display_name,
        })
        return (f"Set {direction} {kind} on track {track_index} to "
                f"'{result.get('display_name', display_name)}'")
    except Exception as e:
        logger.error(f"Error setting track routing: {str(e)}")
        return f"Error setting track routing: {str(e)}"


@mcp.tool()
def set_track_state(ctx: Context, track_index: int, attribute: str, value: bool) -> str:
    """
    Set a track's mute / solo / arm state.

    Parameters:
    - track_index: Index of the track
    - attribute: One of "mute", "solo", "arm"
    - value: True or False
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_state", {
            "track_index": track_index,
            "attribute": attribute,
            "value": value,
        })
        return f"Set {attribute} on track {track_index} to {result.get('value', value)}"
    except Exception as e:
        logger.error(f"Error setting track state: {str(e)}")
        return f"Error setting track state: {str(e)}"


# ---------------------------------------------------------------------------
# Tier 3 — Arrangement view + session control
# ---------------------------------------------------------------------------

@mcp.tool()
def get_arrangement_clips(ctx: Context, track_index: int) -> str:
    """
    List clips on a track's arrangement view.

    Parameters:
    - track_index: Index of the track
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_arrangement_clips", {"track_index": track_index})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting arrangement clips: {str(e)}")
        return f"Error getting arrangement clips: {str(e)}"


@mcp.tool()
def get_full_session(ctx: Context, include_params: bool = True) -> str:
    """
    Return the complete session state in one call: session globals, all tracks with
    devices (and optionally all device parameters), all return tracks, and master track.

    Parameters:
    - include_params: If True (default), include all device parameter values and ranges.
                      Set False for a lightweight overview without parameter details.

    Size warning: with `include_params=True`, the response scales as
    tracks * devices * params. On sessions with > ~10 tracks and several devices each,
    the JSON commonly exceeds the model's tool-result token cap and gets truncated to
    a file. Strategy:
      - First call with `include_params=False` to get the structure (cheap).
      - Then call `get_device_parameters(track, device)` for the specific devices
        you actually care about, OR
      - Call this with `include_params=True` accepting the truncation, then `jq`
        over the saved file at /tmp or the tool-results directory.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_full_session", {"include_params": include_params})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting full session: {str(e)}")
        return f"Error getting full session: {str(e)}"


@mcp.tool()
def delete_arrangement_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Delete an arrangement clip by its position in the track's arrangement_clips tuple.

    Parameters:
    - track_index: Index of the track
    - clip_index: Position in track.arrangement_clips (as returned by get_arrangement_clips)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("delete_arrangement_clip", {
            "track_index": track_index,
            "clip_index": clip_index,
        })
        return (f"Deleted arrangement clip '{result.get('name', '?')}' "
                f"(start={result.get('start_time', '?')}) on track {track_index}")
    except Exception as e:
        logger.error(f"Error deleting arrangement clip: {str(e)}")
        return f"Error deleting arrangement clip: {str(e)}"


@mcp.tool()
def set_clip_loop_region(
    ctx: Context,
    track_index: int,
    clip_index: int,
    loop_start: float,
    loop_end: float,
) -> str:
    """
    Set the loop region inside a session-view clip (loop brace, not arrangement loop).

    Parameters:
    - track_index: Index of the track
    - clip_index: Session-view slot index
    - loop_start: Loop start in beats (>= 0)
    - loop_end: Loop end in beats (> loop_start, <= clip.length)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_loop_region", {
            "track_index": track_index,
            "clip_index": clip_index,
            "loop_start": loop_start,
            "loop_end": loop_end,
        })
        return (f"Set clip loop: start={result.get('loop_start', loop_start)}, "
                f"end={result.get('loop_end', loop_end)} on track {track_index}, "
                f"slot {clip_index}")
    except Exception as e:
        logger.error(f"Error setting clip loop region: {str(e)}")
        return f"Error setting clip loop region: {str(e)}"


@mcp.tool()
def jump_to_beat(ctx: Context, beat: float) -> str:
    """
    Move the arrangement playhead to an absolute beat position.

    Parameters:
    - beat: Target beat (>= 0). 4 beats = 1 bar at 4/4.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("jump_to_beat", {"beat": beat})
        return f"Jumped to beat {result.get('beat', beat)}"
    except Exception as e:
        logger.error(f"Error jumping to beat: {str(e)}")
        return f"Error jumping to beat: {str(e)}"


@mcp.tool()
def load_instrument_or_effect(ctx: Context, track_index: int, uri: str) -> str:
    """
    Load an instrument or effect onto a track using its URI.
    
    Parameters:
    - track_index: The index of the track to load the instrument on
    - uri: The URI of the instrument or effect to load (e.g., 'query:Synths#Instrument%20Rack:Bass:FileId_5116')
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": uri
        })
        
        # Check if the instrument was loaded successfully
        if result.get("loaded", False):
            new_devices = result.get("new_devices", [])
            if new_devices:
                return f"Loaded instrument with URI '{uri}' on track {track_index}. New devices: {', '.join(new_devices)}"
            else:
                devices = result.get("devices_after", [])
                return f"Loaded instrument with URI '{uri}' on track {track_index}. Devices on track: {', '.join(devices)}"
        else:
            return f"Failed to load instrument with URI '{uri}'"
    except Exception as e:
        logger.error(f"Error loading instrument by URI: {str(e)}")
        return f"Error loading instrument by URI: {str(e)}"

@mcp.tool()
def add_master_device(ctx: Context, uri: str) -> str:
    """
    Add an instrument or effect to the MASTER track via browser.

    Closes the decision-matrix gap that master devices could only be PARAMETER-tuned
    (set_master_device_parameter) but not ADDED. Now adds work too — validated
    2026-05-17 against Live 12 LOM stubs: `view.selected_track = master_track +
    browser.load_item(item)` is the supported path.

    Parameters:
    - uri: Browser-item URI, e.g. 'query:AudioFx#EQ%20Eight' or
           'query:AudioFx#Glue%20Compressor' or 'query:AudioFx#Limiter'.
           Get URIs from get_browser_items_at_path('audio_effects').
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("load_master_item", {"item_uri": uri})
        if result.get("loaded"):
            new_devices = result.get("new_devices", [])
            return (f"Added '{result.get('item_name')}' to Master. "
                    f"New device(s): {', '.join(new_devices) if new_devices else '(none — chain unchanged)'}. "
                    f"Master chain now: {', '.join(result.get('devices_after', []))}")
        return f"Failed to add '{uri}' on Master"
    except Exception as e:
        logger.error(f"Error adding master device: {e}")
        return f"Error adding master device: {e}"


@mcp.tool()
def add_return_device(ctx: Context, return_index: int, uri: str) -> str:
    """
    Add an instrument or effect to a RETURN track via browser.

    Closes the decision-matrix gap for return tracks — previously you could
    only tune return-device parameters, not add new devices. Now both work.

    Parameters:
    - return_index: 0 = A, 1 = B, 2 = C, ...
    - uri: Browser-item URI (same format as load_instrument_or_effect).
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("load_return_item", {
            "return_index": return_index,
            "item_uri": uri,
        })
        if result.get("loaded"):
            new_devices = result.get("new_devices", [])
            return (f"Added '{result.get('item_name')}' to return {return_index} "
                    f"({result.get('track_name')}). New: {', '.join(new_devices) if new_devices else '(none)'}. "
                    f"Chain now: {', '.join(result.get('devices_after', []))}")
        return f"Failed to add '{uri}' on return {return_index}"
    except Exception as e:
        logger.error(f"Error adding return device: {e}")
        return f"Error adding return device: {e}"


@mcp.tool()
def create_return_track(ctx: Context) -> str:
    """
    Create a new return track in the session.

    Wraps Live 12's `song.create_return_track()` (validated against Live 12
    Push2 Remote Script stubs, browser_component.py:825). Previously had to
    create returns manually in the Live UI.

    Returns the index of the newly created return track.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_return_track", {})
        if result.get("created"):
            return (f"Created return track at index {result.get('return_index')}: "
                    f"'{result.get('name')}'. Total returns now: {result.get('total_returns')}")
        return "Failed to create return track"
    except Exception as e:
        logger.error(f"Error creating return track: {e}")
        return f"Error creating return track: {e}"


@mcp.tool()
def audio_to_midi_clip(ctx: Context, track_index: int, clip_index: int,
                        conversion_type: str = "melody") -> str:
    """
    Convert an audio clip to MIDI using Live 12's native AI transcription.

    Creates a new MIDI track containing the converted clip. Live's native
    melody/harmony/drums extraction — often produces better results than
    librosa-based pipelines on polyphonic content because it's trained on
    the same source material Ableton ships in Packs.

    Parameters:
    - track_index: Track containing the source audio clip
    - clip_index: Clip slot of the source clip
    - conversion_type: "melody" | "harmony" | "drums" (default "melody")

    The source clip must be an audio clip (not MIDI). Validated 2026-05-17
    against Live 12 Push2/convert.py stubs.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("audio_to_midi_clip", {
            "track_index": track_index,
            "clip_index": clip_index,
            "conversion_type": conversion_type,
        })
        if result.get("converted"):
            return (f"Converted '{result.get('source_clip')}' on track "
                    f"'{result.get('source_track')}' to {conversion_type} MIDI. "
                    f"New track at index {result.get('new_track_index')}: "
                    f"'{result.get('new_track_name')}'")
        return f"Failed to convert clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error in audio_to_midi_clip: {e}")
        return f"Error in audio_to_midi_clip: {e}"


@mcp.tool()
def create_drum_rack_from_audio_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Live 12: convert an audio clip into a Drum Rack on a new track.

    Equivalent to Push2's "convert audio clip to drum rack" feature. Useful
    for turning a drum loop into a playable rack.

    Parameters:
    - track_index, clip_index: locate the source audio clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_drum_rack_from_audio_clip", {
            "track_index": track_index,
            "clip_index": clip_index,
        })
        if result.get("converted"):
            return (f"Created Drum Rack from '{result.get('source_clip')}'. "
                    f"New track at index {result.get('new_track_index')}: "
                    f"'{result.get('new_track_name')}'")
        return f"Failed to create drum rack from clip"
    except Exception as e:
        logger.error(f"Error in create_drum_rack_from_audio_clip: {e}")
        return f"Error in create_drum_rack_from_audio_clip: {e}"


@mcp.tool()
def create_midi_track_from_audio_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Live 12: create a new MIDI track with a Simpler loaded from the audio clip.

    This is Push2's "audio clip → Simpler track" workflow. The new MIDI track
    has a Simpler instrument pre-loaded with the source clip; trigger via MIDI.

    Parameters:
    - track_index, clip_index: locate the source audio clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_midi_track_from_audio_clip", {
            "track_index": track_index,
            "clip_index": clip_index,
        })
        if result.get("converted"):
            return (f"Created MIDI track with Simpler from '{result.get('source_clip')}'. "
                    f"New track at index {result.get('new_track_index')}: "
                    f"'{result.get('new_track_name')}'")
        return f"Failed to create MIDI track from clip"
    except Exception as e:
        logger.error(f"Error in create_midi_track_from_audio_clip: {e}")
        return f"Error in create_midi_track_from_audio_clip: {e}"


@mcp.tool()
def move_track_devices_to_drum_pad(ctx: Context, track_index: int) -> str:
    """
    Live 12: move a track's device chain into a new Drum Rack pad.

    Useful for organizing layered drum tracks into a single drum rack —
    e.g. take three audio tracks ("Kick", "Snare", "Hat") and consolidate
    each into a pad of one master Drum Rack track.

    Parameters:
    - track_index: source track whose devices will be moved
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("move_track_devices_to_drum_pad", {
            "track_index": track_index,
        })
        if result.get("moved"):
            return (f"Moved devices from '{result.get('source_track')}' to a new "
                    f"Drum Rack pad. Total tracks: {result.get('total_tracks')}")
        return f"Failed to move track devices"
    except Exception as e:
        logger.error(f"Error in move_track_devices_to_drum_pad: {e}")
        return f"Error in move_track_devices_to_drum_pad: {e}"


@mcp.tool()
def convert_sliced_simpler_to_drum_rack(ctx: Context, track_index: int, device_index: int) -> str:
    """
    Live 12: convert a Simpler (in sliced mode) on a track into a full Drum Rack.

    The Simpler must be in slice mode for this to work. Each slice becomes
    a separate drum pad. Useful when you want per-slice control (EQ, FX,
    velocity) that Simpler doesn't natively offer.

    Parameters:
    - track_index: track containing the Simpler device
    - device_index: index of the Simpler device on that track
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("convert_sliced_simpler_to_drum_rack", {
            "track_index": track_index,
            "device_index": device_index,
        })
        if result.get("converted"):
            return (f"Converted '{result.get('source_device')}' on track "
                    f"'{result.get('track')}' to Drum Rack. Chain now: "
                    f"{', '.join(result.get('devices_after', []))}")
        return f"Failed to convert sliced Simpler"
    except Exception as e:
        logger.error(f"Error in convert_sliced_simpler_to_drum_rack: {e}")
        return f"Error in convert_sliced_simpler_to_drum_rack: {e}"


@mcp.tool()
def fire_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Start playing a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("fire_clip", {
            "track_index": track_index,
            "clip_index": clip_index
        })
        return f"Started playing clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error firing clip: {str(e)}")
        return f"Error firing clip: {str(e)}"

@mcp.tool()
def stop_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Stop playing a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("stop_clip", {
            "track_index": track_index,
            "clip_index": clip_index
        })
        return f"Stopped clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error stopping clip: {str(e)}")
        return f"Error stopping clip: {str(e)}"

@mcp.tool()
def start_playback(ctx: Context) -> str:
    """Start playing the Ableton session."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("start_playback")
        return "Started playback"
    except Exception as e:
        logger.error(f"Error starting playback: {str(e)}")
        return f"Error starting playback: {str(e)}"

@mcp.tool()
def stop_playback(ctx: Context) -> str:
    """Stop playing the Ableton session."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("stop_playback")
        return "Stopped playback"
    except Exception as e:
        logger.error(f"Error stopping playback: {str(e)}")
        return f"Error stopping playback: {str(e)}"

@mcp.tool()
def get_browser_tree(ctx: Context, category_type: str = "all") -> str:
    """
    Get a hierarchical tree of browser categories from Ableton.
    
    Parameters:
    - category_type: Type of categories to get ('all', 'instruments', 'sounds', 'drums', 'audio_effects', 'midi_effects')
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_browser_tree", {
            "category_type": category_type
        })
        
        # Check if we got any categories
        if "available_categories" in result and len(result.get("categories", [])) == 0:
            available_cats = result.get("available_categories", [])
            return (f"No categories found for '{category_type}'. "
                   f"Available browser categories: {', '.join(available_cats)}")
        
        # Format the tree in a more readable way
        total_folders = result.get("total_folders", 0)
        formatted_output = f"Browser tree for '{category_type}' (showing {total_folders} folders):\n\n"
        
        def format_tree(item, indent=0):
            output = ""
            if item:
                prefix = "  " * indent
                name = item.get("name", "Unknown")
                path = item.get("path", "")
                has_more = item.get("has_more", False)
                
                # Add this item
                output += f"{prefix}• {name}"
                if path:
                    output += f" (path: {path})"
                if has_more:
                    output += " [...]"
                output += "\n"
                
                # Add children
                for child in item.get("children", []):
                    output += format_tree(child, indent + 1)
            return output
        
        # Format each category
        for category in result.get("categories", []):
            formatted_output += format_tree(category)
            formatted_output += "\n"
        
        return formatted_output
    except Exception as e:
        error_msg = str(e)
        if "Browser is not available" in error_msg:
            logger.error(f"Browser is not available in Ableton: {error_msg}")
            return f"Error: The Ableton browser is not available. Make sure Ableton Live is fully loaded and try again."
        elif "Could not access Live application" in error_msg:
            logger.error(f"Could not access Live application: {error_msg}")
            return f"Error: Could not access the Ableton Live application. Make sure Ableton Live is running and the Remote Script is loaded."
        else:
            logger.error(f"Error getting browser tree: {error_msg}")
            return f"Error getting browser tree: {error_msg}"

@mcp.tool()
def get_browser_items_at_path(ctx: Context, path: str) -> str:
    """
    Get browser items at a specific path in Ableton's browser.
    
    Parameters:
    - path: Path in the format "category/folder/subfolder"
            where category is one of the available browser categories in Ableton
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_browser_items_at_path", {
            "path": path
        })
        
        # Check if there was an error with available categories
        if "error" in result and "available_categories" in result:
            error = result.get("error", "")
            available_cats = result.get("available_categories", [])
            return (f"Error: {error}\n"
                   f"Available browser categories: {', '.join(available_cats)}")
        
        return json.dumps(result, indent=2)
    except Exception as e:
        error_msg = str(e)
        if "Browser is not available" in error_msg:
            logger.error(f"Browser is not available in Ableton: {error_msg}")
            return f"Error: The Ableton browser is not available. Make sure Ableton Live is fully loaded and try again."
        elif "Could not access Live application" in error_msg:
            logger.error(f"Could not access Live application: {error_msg}")
            return f"Error: Could not access the Ableton Live application. Make sure Ableton Live is running and the Remote Script is loaded."
        elif "Unknown or unavailable category" in error_msg:
            logger.error(f"Invalid browser category: {error_msg}")
            return f"Error: {error_msg}. Please check the available categories using get_browser_tree."
        elif "Path part" in error_msg and "not found" in error_msg:
            logger.error(f"Path not found: {error_msg}")
            return f"Error: {error_msg}. Please check the path and try again."
        else:
            logger.error(f"Error getting browser items at path: {error_msg}")
            return f"Error getting browser items at path: {error_msg}"

@mcp.tool()
def load_drum_kit(ctx: Context, track_index: int, rack_uri: str, kit_path: str) -> str:
    """
    Load a drum rack and then load a specific drum kit into it.
    
    Parameters:
    - track_index: The index of the track to load on
    - rack_uri: The URI of the drum rack to load (e.g., 'Drums/Drum Rack')
    - kit_path: Path to the drum kit inside the browser (e.g., 'drums/acoustic/kit1')
    """
    try:
        ableton = get_ableton_connection()
        
        # Step 1: Load the drum rack
        result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": rack_uri
        })
        
        if not result.get("loaded", False):
            return f"Failed to load drum rack with URI '{rack_uri}'"
        
        # Step 2: Get the drum kit items at the specified path
        kit_result = ableton.send_command("get_browser_items_at_path", {
            "path": kit_path
        })
        
        if "error" in kit_result:
            return f"Loaded drum rack but failed to find drum kit: {kit_result.get('error')}"
        
        # Step 3: Find a loadable drum kit
        kit_items = kit_result.get("items", [])
        loadable_kits = [item for item in kit_items if item.get("is_loadable", False)]
        
        if not loadable_kits:
            return f"Loaded drum rack but no loadable drum kits found at '{kit_path}'"
        
        # Step 4: Load the first loadable kit
        kit_uri = loadable_kits[0].get("uri")
        load_result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": kit_uri
        })
        
        return f"Loaded drum rack and kit '{loadable_kits[0].get('name')}' on track {track_index}"
    except Exception as e:
        logger.error(f"Error loading drum kit: {str(e)}")
        return f"Error loading drum kit: {str(e)}"


# ---------------------------------------------------------------------------
# Clip envelope (live automation) tools
#
# IMPORTANT: These tools write to *session-view clip* envelopes — the colored
# automation lane drawn on a clip in the Session view. They do NOT write to
# arrangement-view automation (track-level lanes in the Arrangement view).
# For arrangement automation, close Ableton and use als_lib.add_automation().
# ---------------------------------------------------------------------------

@mcp.tool()
def get_clip_envelope(
    ctx: Context,
    track_index: int,
    clip_index: int,
    param_path: str,
    sample_interval: float = 0.25,
    times: Optional[List[float]] = None,
    location: str = "session",
) -> str:
    """
    Read an automation envelope from a clip (session or arrangement).

    LOM does not expose envelope points directly — values are sampled from the
    envelope. By default, samples every 0.25 beats across the clip length.
    Pass `times` to specify exact sample positions instead.

    Parameters:
    - track_index: Track containing the clip
    - clip_index: Index — slot index when location='session',
                  arrangement_clips index when location='arrangement'
    - param_path: Parameter to read. Forms:
        "mixer.volume" / "mixer.panning" / "mixer.send:N"
        "device:N.parameter:M"  (device index + param index)
        "device:N.<NAME>"       (device index + param name)
    - sample_interval: Spacing between samples in beats (ignored if `times` given)
    - times: Explicit list of sample positions in beats
    - location: "session" (default) reads from track.clip_slots[clip_index];
                "arrangement" reads from track.arrangement_clips[clip_index].
                Use get_arrangement_clips() to find arrangement clip indices.

    Returns JSON: {parameter, exists, samples:[{time,value},...], param_min, param_max, clip_length}
    """
    try:
        ableton = get_ableton_connection()
        payload = {
            "track_index": track_index,
            "clip_index": clip_index,
            "param_path": param_path,
            "sample_interval": sample_interval,
            "location": location,
        }
        if times is not None:
            payload["times"] = times
        result = ableton.send_command("get_clip_envelope", payload)
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting clip envelope: {str(e)}")
        return f"Error getting clip envelope: {str(e)}"


@mcp.tool()
def set_clip_envelope_point(
    ctx: Context,
    track_index: int,
    clip_index: int,
    param_path: str,
    time: float,
    value: float,
    length: float = 0.0,
    location: str = "session",
) -> str:
    """
    Insert a single automation point/step on a clip envelope (session or arrangement).

    Creates the envelope automatically on first write.

    Parameters:
    - track_index, clip_index: Locate the clip (see `location`)
    - param_path: e.g. "mixer.volume", "mixer.send:0", "device:0.parameter:1"
    - time: Position in beats (0 = clip start)
    - value: Target value (clamped to parameter's [min, max])
    - length: Step duration in beats (0 = single point, no plateau)
    - location: "session" or "arrangement"
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_envelope_point", {
            "track_index": track_index,
            "clip_index": clip_index,
            "param_path": param_path,
            "time": time,
            "value": value,
            "length": length,
            "location": location,
        })
        clamped_note = " (clamped)" if result.get("clamped") else ""
        return (f"Inserted point on '{result.get('parameter', param_path)}' at "
                f"time={result.get('time', time)}, value={result.get('value', value)}"
                f"{clamped_note}")
    except Exception as e:
        logger.error(f"Error setting clip envelope point: {str(e)}")
        return f"Error setting clip envelope point: {str(e)}"


@mcp.tool()
def set_clip_envelope_curve(
    ctx: Context,
    track_index: int,
    clip_index: int,
    param_path: str,
    points: List[Dict[str, float]],
    replace: bool = True,
    location: str = "session",
) -> str:
    """
    Bulk-write an automation curve onto a clip envelope (session or arrangement).

    Each point is a dict {time, value} or {time, value, length}.
    By default, replaces any existing envelope on the parameter.

    Parameters:
    - track_index, clip_index: Locate the clip (see `location`)
    - param_path: e.g. "mixer.volume", "mixer.send:0", "device:0.<NAME>"
    - points: e.g. [{"time": 0, "value": 0.65, "length": 16},
                    {"time": 16, "value": 0.55, "length": 8},
                    {"time": 24, "value": 0.85, "length": 8}]
    - replace: If True (default), clears existing envelope first.
               If False, points are added to existing curve.
    - location: "session" or "arrangement"

    Each point is converted to envelope.insert_step(time, length, value).
    NOTE: length=0 produces a degenerate step that doesn't persist.
    Always set length to cover the duration the value should hold.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_envelope_curve", {
            "track_index": track_index,
            "clip_index": clip_index,
            "param_path": param_path,
            "points": points,
            "replace": replace,
            "location": location,
        })
        action = "replaced" if replace else "appended"
        return (f"Curve {action} on '{result.get('parameter', param_path)}': "
                f"{result.get('points_inserted', 0)} points inserted, "
                f"{result.get('clamped_count', 0)} clamped to range")
    except Exception as e:
        logger.error(f"Error setting clip envelope curve: {str(e)}")
        return f"Error setting clip envelope curve: {str(e)}"


@mcp.tool()
def re_enable_automation(
    ctx: Context,
    track_index: Optional[int] = None,
    device_index: Optional[int] = None,
    parameter: Union[int, str, None] = None,
) -> str:
    """
    Re-enable automation. With no arguments, re-enables song-wide (covers any
    parameter currently in 'overridden' state). With track_index + device_index
    + parameter, re-enables a single parameter.

    Use this when you've manually moved a knob whose envelope has been written —
    Live puts the parameter into 'overridden' mode and stops following the
    envelope until re-enabled.
    """
    try:
        ableton = get_ableton_connection()
        payload = {}
        if track_index is not None:
            payload["track_index"] = track_index
        if device_index is not None:
            payload["device_index"] = device_index
        if parameter is not None:
            payload["parameter"] = parameter
        result = ableton.send_command("re_enable_automation", payload)
        if result.get("scope") == "global":
            return "Re-enabled all overridden automation song-wide"
        return (f"Re-enabled automation on '{result.get('parameter')}' "
                f"(state={result.get('automation_state')})")
    except Exception as e:
        logger.error(f"Error re-enabling automation: {str(e)}")
        return f"Error re-enabling automation: {str(e)}"


@mcp.tool()
def get_parameter_automation_state(
    ctx: Context,
    track_index: int,
    device_index: int,
    parameter: Union[int, str],
) -> str:
    """
    Read the automation state of a device parameter.

    Returns automation_state: 0=none, 1=played (following automation),
    2=overridden (user moved the knob, automation paused).
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_parameter_automation_state", {
            "track_index": track_index,
            "device_index": device_index,
            "parameter": parameter,
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error reading automation state: {str(e)}")
        return f"Error reading automation state: {str(e)}"


# ---------------------------------------------------------------------------
# Rack chain / drum pad tools
#
# Works on Audio Effect Racks, Instrument Racks, MIDI Effect Racks, and
# Drum Racks. Drum pads are addressed by MIDI note (0-127). Rack macros
# (1-16) are NOT in these tools — they're already accessible via
# set_device_parameter with parameter="Macro N".
# ---------------------------------------------------------------------------

@mcp.tool()
def get_rack_chains(
    ctx: Context,
    track_index: int,
    device_index: int,
) -> str:
    """
    List all chains inside a rack device (any rack type).

    Returns JSON: {rack_name, is_drum_rack, chain_count,
    chains: [{index, name, mute, solo, color_index, volume, panning, sends,
              device_count, devices:[{index, name, class_name}]}]}
    Use the chain `index` with set_chain_state / set_chain_mixer_value.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_rack_chains", {
            "track_index": track_index,
            "device_index": device_index,
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting rack chains: {str(e)}")
        return f"Error getting rack chains: {str(e)}"


@mcp.tool()
def get_drum_pads(
    ctx: Context,
    track_index: int,
    device_index: int,
    only_non_empty: bool = True,
) -> str:
    """
    List drum pads on a Drum Rack. Pads are indexed by MIDI note (0-127).

    By default returns only pads with chains assigned (most kits have ~10-20
    populated pads out of 128). Set only_non_empty=False to see the full grid.

    Returns JSON: {rack_name, pad_count, pads:[{note, name, mute, solo,
    chain_count, chain_index, devices:[...]}]}.
    `chain_index` is the position in device.chains so you can use
    set_chain_mixer_value to control per-pad volume/sends.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_drum_pads", {
            "track_index": track_index,
            "device_index": device_index,
            "only_non_empty": only_non_empty,
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting drum pads: {str(e)}")
        return f"Error getting drum pads: {str(e)}"


@mcp.tool()
def set_chain_state(
    ctx: Context,
    track_index: int,
    device_index: int,
    chain_index: int,
    attribute: str,
    value: bool,
) -> str:
    """
    Toggle mute or solo on a rack chain.

    Parameters:
    - track_index, device_index: locate the rack
    - chain_index: position in device.chains (from get_rack_chains)
    - attribute: "mute" or "solo"
    - value: True or False

    For drum racks, this sets state on the underlying chain. To mute a drum
    *pad* (which is the user-visible mute in Ableton's UI), use
    set_drum_pad_state instead.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_chain_state", {
            "track_index": track_index,
            "device_index": device_index,
            "chain_index": chain_index,
            "attribute": attribute,
            "value": value,
        })
        return (f"Chain '{result.get('name', chain_index)}' "
                f"{result.get('attribute', attribute)} = {result.get('value', value)}")
    except Exception as e:
        logger.error(f"Error setting chain state: {str(e)}")
        return f"Error setting chain state: {str(e)}"


@mcp.tool()
def set_chain_mixer_value(
    ctx: Context,
    track_index: int,
    device_index: int,
    chain_index: int,
    param: str,
    value: float,
) -> str:
    """
    Set volume/panning/send on a rack chain's mixer.

    Parameters:
    - track_index, device_index: locate the rack
    - chain_index: position in device.chains (from get_rack_chains)
    - param: "volume" / "panning" / "send:N"
    - value: clamped to the parameter's [min, max]
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_chain_mixer_value", {
            "track_index": track_index,
            "device_index": device_index,
            "chain_index": chain_index,
            "param": param,
            "value": value,
        })
        clamped = " (clamped)" if result.get("clamped") else ""
        return (f"Chain '{result.get('name', chain_index)}' {param} = "
                f"{result.get('value', value)}{clamped}")
    except Exception as e:
        logger.error(f"Error setting chain mixer value: {str(e)}")
        return f"Error setting chain mixer value: {str(e)}"


@mcp.tool()
def get_master_device_parameters(
    ctx: Context,
    device_index: int,
) -> str:
    """
    List all parameters on a device on the MASTER track.

    The master track holds devices like Utility/EQ Eight/Glue Compressor/Limiter
    that aren't reachable via the regular track-indexed tools (track_index 0..N-1
    rejects master). Use get_full_session() with include_params=True to see the
    master device list and their indices.

    Returns JSON list of {index, name, value, min, max, is_enabled}.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_master_device_parameters", {
            "device_index": device_index,
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting master device parameters: {str(e)}")
        return f"Error getting master device parameters: {str(e)}"


@mcp.tool()
def set_master_device_parameter(
    ctx: Context,
    device_index: int,
    parameter: Union[int, str],
    value: float,
) -> str:
    """
    Set a parameter on a device on the MASTER track.

    Mirrors set_device_parameter but reaches song.master_track.devices[N]
    instead of song.tracks[N]. Use this for the master mastering chain
    (Utility gain, EQ bands, Glue threshold/ratio/attack/release/makeup,
    Limiter ceiling/lookahead/true-peak, etc.).

    `parameter`: integer index or name string (e.g. "Threshold", "Ceiling").
    `value`: clamped to the parameter's [min, max] range.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_master_device_parameter", {
            "device_index": device_index,
            "parameter": parameter,
            "value": value,
        })
        clamped = " (clamped)" if result.get("clamped") else ""
        return (f"Set {result.get('name', parameter)} on master device "
                f"{device_index} to {result.get('value', value)}{clamped}")
    except Exception as e:
        logger.error(f"Error setting master device parameter: {str(e)}")
        return f"Error setting master device parameter: {str(e)}"


@mcp.tool()
def get_return_device_parameters(
    ctx: Context,
    return_index: int,
    device_index: int,
) -> str:
    """
    List all parameters on a device on a RETURN track.

    Returns are addressed by `return_index` (0 = A-Reverb, 1 = B-Delay, etc.).
    Use get_return_track_info() to see what's on each return.

    Returns JSON list of {index, name, value, min, max, is_enabled}.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_return_device_parameters", {
            "return_index": return_index,
            "device_index": device_index,
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting return device parameters: {str(e)}")
        return f"Error getting return device parameters: {str(e)}"


@mcp.tool()
def set_return_device_parameter(
    ctx: Context,
    return_index: int,
    device_index: int,
    parameter: Union[int, str],
    value: float,
) -> str:
    """
    Set a parameter on a device on a RETURN track.

    Mirrors set_device_parameter but reaches song.return_tracks[R].devices[D]
    instead of song.tracks[T].devices[D]. Use this for return-track effect
    parameters (e.g., Reverb's PreDelay, DecayTime, Delay's Feedback, etc.).

    `parameter`: integer index or name string.
    `value`: clamped to [min, max].
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_return_device_parameter", {
            "return_index": return_index,
            "device_index": device_index,
            "parameter": parameter,
            "value": value,
        })
        clamped = " (clamped)" if result.get("clamped") else ""
        return (f"Set {result.get('name', parameter)} on return {return_index} "
                f"device {device_index} to {result.get('value', value)}{clamped}")
    except Exception as e:
        logger.error(f"Error setting return device parameter: {str(e)}")
        return f"Error setting return device parameter: {str(e)}"


@mcp.tool()
def set_drum_pad_state(
    ctx: Context,
    track_index: int,
    device_index: int,
    pad_note: int,
    attribute: str,
    value: bool,
) -> str:
    """
    Toggle mute or solo on a drum rack pad (addressed by MIDI note).

    Parameters:
    - track_index, device_index: locate the drum rack
    - pad_note: MIDI note number 0..127 (e.g., 36 = C1, the standard kick pad)
    - attribute: "mute" or "solo"
    - value: True or False

    Pads with no chain assigned can still be muted/soloed (no-op audibly).
    Errors if the device isn't a drum rack.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_drum_pad_state", {
            "track_index": track_index,
            "device_index": device_index,
            "pad_note": pad_note,
            "attribute": attribute,
            "value": value,
        })
        empty = " (empty pad)" if result.get("is_empty") else ""
        return (f"Drum pad note={result.get('pad_note', pad_note)} "
                f"'{result.get('pad_name', '')}' "
                f"{result.get('attribute', attribute)} = {result.get('value', value)}{empty}")
    except Exception as e:
        logger.error(f"Error setting drum pad state: {str(e)}")
        return f"Error setting drum pad state: {str(e)}"


# ============================================================================
# High-value 6 (2026-05-17): scale, quantize, cues, grooves, warp, selection
# ============================================================================


@mcp.tool()
def get_song_scale(ctx: Context) -> str:
    """
    Read the Live 12 global scale/key (Song.scale_name, root_note, in_key).

    Live 12 added scale-aware features (MIDI tools, browser filters, etc.).
    Use this to discover the current key before generating MIDI; pair with
    set_song_scale to lock the session to a specific key.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_song_scale", {})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error reading song scale: {e}")
        return f"Error reading song scale: {e}"


@mcp.tool()
def set_song_scale(
    ctx: Context,
    scale_name: str = None,
    root_note: int = None,
    in_key: bool = None,
) -> str:
    """
    Set the Live 12 global scale/key. Pass only the fields you want to change.

    Parameters:
    - scale_name: e.g. "Major", "Minor", "Dorian", "Phrygian", "Mixolydian",
                  "Aeolian", "Locrian", "Harmonic Minor", "Melodic Minor",
                  "Whole Tone", "Pentatonic Major", "Pentatonic Minor", "Blues"
    - root_note: 0..11 (C=0, C#=1, D=2, ... B=11)
    - in_key: True to enable scale highlighting / scale-aware tools

    Example: F minor → set_song_scale(scale_name="Minor", root_note=5, in_key=True)
    """
    try:
        ableton = get_ableton_connection()
        params = {}
        if scale_name is not None:
            params["scale_name"] = scale_name
        if root_note is not None:
            params["root_note"] = int(root_note)
        if in_key is not None:
            params["in_key"] = bool(in_key)
        if not params:
            return "Error: provide at least one of scale_name/root_note/in_key"
        result = ableton.send_command("set_song_scale", params)
        cur = result.get("current", {})
        return (f"Scale → {cur.get('root_name', '?')} {cur.get('scale_name', '?')}, "
                f"in_key={cur.get('in_key')}. Changed: {result.get('changed')}")
    except Exception as e:
        logger.error(f"Error setting song scale: {e}")
        return f"Error setting song scale: {e}"


@mcp.tool()
def quantize_clip_notes(
    ctx: Context,
    track_index: int,
    clip_index: int,
    grid: str = "1/16",
    amount: float = 1.0,
    quantize_pitch: bool = False,
) -> str:
    """
    Quantize notes in a MIDI clip via Clip.quantize(grid, amount).

    Parameters:
    - grid: '1/4', '1/8', '1/8t', '1/16', '1/16t', '1/32', or 'none'
            (also accepts long forms: 'quarter', 'eighth', etc.)
    - amount: 0.0..1.0 (1.0 = fully snap to grid, 0.5 = halfway)
    - quantize_pitch: if True, also snap note pitches to scale (Live 12)

    Errors on audio clips. Useful for cleaning up MIDI captures or
    nudging hand-played MIDI toward the grid without losing groove.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("quantize_clip_notes", {
            "track_index": track_index,
            "clip_index": clip_index,
            "grid": grid,
            "amount": amount,
            "quantize_pitch": quantize_pitch,
        })
        pitch = " + pitch" if result.get("quantize_pitch_applied") else ""
        return (f"Quantized '{result.get('name')}' to grid={grid} "
                f"amount={result.get('amount')}{pitch}")
    except Exception as e:
        logger.error(f"Error quantizing clip: {e}")
        return f"Error quantizing clip: {e}"


@mcp.tool()
def get_cue_points(ctx: Context) -> str:
    """
    List all cue points (locators) in the song with their times and names.

    Cue points anchor arrangement navigation — your intro/build/drop markers.
    Pair with jump_to_cue to navigate between them.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_cue_points", {})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error reading cue points: {e}")
        return f"Error reading cue points: {e}"


@mcp.tool()
def set_or_delete_cue(ctx: Context, time: float = None, name: str = None) -> str:
    """
    Toggle a cue point at the CURRENT PLAYBACK POSITION. If a cue exists
    at that position, it's DELETED. Otherwise CREATED.

    LIVE API LIMITATION (Live 12.3.7, verified 2026-05-17): the `time`
    argument cannot reliably move the playhead — `current_song_time` is
    read-only when transport is stopped. Behavior:
      - With transport STOPPED: `time` is effectively ignored; the cue
        lands at wherever the playhead last left off. Response will
        include a `warning` field stating the actual landing time.
      - With transport PLAYING: write to `current_song_time` may take
        effect (untested), but timing is approximate.

    Reliable usage:
      - Omit `time` entirely → cue at current playhead.
      - To place at a specific time: scrub Live's UI cursor to that
        position first, then call this tool without `time`.

    Parameters:
    - time: optional beat position (best-effort; see limitation above)
    - name: optional name for the new cue
    """
    try:
        ableton = get_ableton_connection()
        params = {}
        if time is not None:
            params["time"] = float(time)
        if name is not None:
            params["name"] = name
        result = ableton.send_command("set_or_delete_cue", params)
        # Surface the full result including any time_warning so callers can
        # see when Live snapped/clamped/rejected a requested time.
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error toggling cue: {e}")
        return f"Error toggling cue: {e}"


@mcp.tool()
def delete_cue_by_index(ctx: Context, cue_index: int) -> str:
    """
    Delete a cue point by its index in `Song.cue_points`.

    Uses `CuePoint.jump()` (which moves the playhead including
    `current_song_time`) followed by `set_or_delete_cue()`. This is the
    only reliable way to delete a specific cue when transport is stopped,
    because direct `current_song_time` writes are read-only in that state.

    Parameters:
    - cue_index: 0-based index from get_cue_points()
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("delete_cue_by_index",
                                       {"cue_index": cue_index})
        return (f"Deleted cue[{cue_index}] '{result.get('cue_name')}' "
                f"at time {result.get('cue_time')}. "
                f"Total cues now: {result.get('total_cues_after')}")
    except Exception as e:
        logger.error(f"Error deleting cue: {e}")
        return f"Error deleting cue: {e}"


@mcp.tool()
def jump_to_cue(ctx: Context, direction: str = "next") -> str:
    """
    Jump playback to the next or previous cue point.

    Parameters:
    - direction: "next" or "prev"
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("jump_to_cue", {"direction": direction})
        if result.get("jumped"):
            return f"Jumped {direction} → song time {result.get('current_song_time'):.3f}"
        return f"Did not jump: {result.get('reason')}"
    except Exception as e:
        logger.error(f"Error jumping to cue: {e}")
        return f"Error jumping to cue: {e}"


@mcp.tool()
def get_grooves(ctx: Context) -> str:
    """
    List grooves in the song's groove pool with all their parameters.

    Grooves apply microtiming/velocity templates to clips. Use to inspect
    what's already in the pool, then assign_groove_to_clip to apply.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_grooves", {})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error reading grooves: {e}")
        return f"Error reading grooves: {e}"


@mcp.tool()
def set_groove_params(
    ctx: Context,
    groove_index: int,
    amount: float = None,
    timing: float = None,
    quantization_amount: float = None,
    random: float = None,
    velocity_amount: float = None,
) -> str:
    """
    Tune a groove's parameters in the groove pool.

    Parameters (all 0.0..1.0 unless noted; pass only what you want to change):
    - amount: overall strength of the groove
    - timing: timing strength (microtiming shift)
    - quantization_amount: how strongly the groove pulls notes to grid
    - random: amount of timing randomization
    - velocity_amount: how much the groove shapes velocities

    Use get_grooves first to find groove_index.
    """
    try:
        ableton = get_ableton_connection()
        params = {"groove_index": groove_index}
        for k, v in (("amount", amount), ("timing", timing),
                     ("quantization_amount", quantization_amount),
                     ("random", random), ("velocity_amount", velocity_amount)):
            if v is not None:
                params[k] = float(v)
        result = ableton.send_command("set_groove_params", params)
        return (f"Groove[{result.get('groove_index')}] '{result.get('name')}' "
                f"changed: {result.get('changed')}")
    except Exception as e:
        logger.error(f"Error setting groove params: {e}")
        return f"Error setting groove params: {e}"


@mcp.tool()
def assign_groove_to_clip(
    ctx: Context,
    track_index: int,
    clip_index: int,
    groove_index: int,
) -> str:
    """
    Assign a groove pool entry to a clip.

    LIVE API LIMITATION (Live 12.3.7): clearing a clip's groove via the
    LOM is NOT supported — `clip.groove = None` is rejected by Live's
    C++ binding. To clear, right-click the groove dropdown in Live's
    clip view and select "(none)" manually.

    Parameters:
    - groove_index: 0..N-1 from get_grooves (use get_grooves first to list)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("assign_groove_to_clip", {
            "track_index": track_index,
            "clip_index": clip_index,
            "groove_index": groove_index,
        })
        if result.get("cleared"):
            return f"Cleared groove on clip '{result.get('name')}'"
        return (f"Assigned groove '{result.get('groove_name')}' "
                f"to clip '{result.get('name')}'")
    except Exception as e:
        logger.error(f"Error assigning groove: {e}")
        return f"Error assigning groove: {e}"


@mcp.tool()
def get_clip_warp(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Read the warping state of an audio clip: warping on/off, warp mode,
    and available warp modes.

    Warp modes:
    0=Beats, 1=Tones, 2=Texture, 3=Repitch, 4=Complex, 5=REX, 6=Complex Pro

    Errors on MIDI clips.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_clip_warp", {
            "track_index": track_index,
            "clip_index": clip_index,
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error reading clip warp: {e}")
        return f"Error reading clip warp: {e}"


@mcp.tool()
def set_clip_warping(
    ctx: Context,
    track_index: int,
    clip_index: int,
    warping: bool,
) -> str:
    """
    Toggle warping on/off for an audio clip (Clip.warping).

    When warping is on, Live time-stretches the clip to the project tempo;
    when off, the clip plays at its original tempo.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_warping", {
            "track_index": track_index,
            "clip_index": clip_index,
            "warping": warping,
        })
        return f"Clip '{result.get('name')}' warping={result.get('warping')}"
    except Exception as e:
        logger.error(f"Error setting clip warping: {e}")
        return f"Error setting clip warping: {e}"


@mcp.tool()
def set_warp_mode(
    ctx: Context,
    track_index: int,
    clip_index: int,
    mode: str,
) -> str:
    """
    Set the warp mode of an audio clip.

    Parameters:
    - mode: "Beats", "Tones", "Texture", "Repitch", "Complex", "REX",
            "Complex Pro" (or the corresponding int 0-6)

    Choice matters for recreate-pipeline output: Repitch preserves tone
    color when pitch-shifting; Complex Pro is best for full mixes;
    Beats is for percussive material.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_warp_mode", {
            "track_index": track_index,
            "clip_index": clip_index,
            "mode": mode,
        })
        return (f"Clip '{result.get('name')}' warp_mode = "
                f"{result.get('warp_mode_name')} ({result.get('warp_mode')})")
    except Exception as e:
        logger.error(f"Error setting warp mode: {e}")
        return f"Error setting warp mode: {e}"


@mcp.tool()
def get_selection(ctx: Context) -> str:
    """
    Read what the user (or last MCP write) has selected in Live's UI.

    Reports: selected_track, selected_scene, detail_clip,
    highlighted_clip_slot, selected_parameter, selected_chain.

    Closes the biggest agent perception gap — use this to figure out what
    the producer is currently looking at before making suggestions.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_selection", {})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error reading selection: {e}")
        return f"Error reading selection: {e}"


@mcp.tool()
def set_selection(
    ctx: Context,
    kind: str,
    index: int = None,
    scene_index: int = None,
    return_index: int = None,
    clip_index: int = None,
) -> str:
    """
    Set what's selected in Live's UI.

    Parameters:
    - kind: 'track' | 'return' | 'master' | 'scene' | 'clip'
    - For kind='track': index = 0-based track index
    - For kind='return': return_index = 0..N-1 (A=0, B=1, ...)
    - For kind='master': no additional args
    - For kind='scene': scene_index
    - For kind='clip': index = track_index, clip_index = clip slot index
                       (sets both highlighted_clip_slot and detail_clip)
    """
    try:
        ableton = get_ableton_connection()
        params = {"kind": kind}
        if index is not None:
            params["index"] = int(index)
        if scene_index is not None:
            params["scene_index"] = int(scene_index)
        if return_index is not None:
            params["return_index"] = int(return_index)
        if clip_index is not None:
            params["clip_index"] = int(clip_index)
        result = ableton.send_command("set_selection", params)
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting selection: {e}")
        return f"Error setting selection: {e}"


# ============================================================================
# Transport batch (2026-05-17): metronome, count-in, quantize, time sig,
# session record, punch, tap/nudge tempo
# ============================================================================


@mcp.tool()
def get_transport_state(ctx: Context) -> str:
    """
    Read all song-level transport state in one call.

    Returns: tempo, is_playing, metronome, count_in_duration,
    midi_recording_quantization, clip_trigger_quantization, swing_amount,
    signature_numerator/denominator, session_record, arrangement_overdub,
    back_to_arranger, punch_in, punch_out, loop region, song_length,
    groove_amount.

    Use to inspect current state before changing anything via the other
    transport tools.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_transport_state", {})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error reading transport state: {e}")
        return f"Error reading transport state: {e}"


@mcp.tool()
def set_metronome(ctx: Context, enabled: bool) -> str:
    """
    Toggle Live's metronome on/off (Song.metronome).
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_metronome", {"enabled": enabled})
        return f"Metronome = {result.get('metronome')}"
    except Exception as e:
        logger.error(f"Error setting metronome: {e}")
        return f"Error setting metronome: {e}"


@mcp.tool()
def set_count_in(ctx: Context, bars: int) -> str:
    """
    Set the count-in duration before recording.

    LIVE API LIMITATION (Live 12.3.7, verified 2026-05-17):
    `Song.count_in_duration` is read-only — no programmatic setter exists.
    Change manually via Live's transport bar count-in dropdown or
    Preferences > Record/Warp/Launch > Count-in.

    Parameters:
    - bars: 0 (no count-in), 1, 2, or 4 bars (input validated but call
            will raise NotImplementedError due to LOM limit)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_count_in", {"bars": bars})
        return f"Count-in = {result.get('count_in_duration')} bar(s)"
    except Exception as e:
        logger.error(f"Error setting count-in: {e}")
        return f"Error setting count-in: {e}"


@mcp.tool()
def set_record_quantization(
    ctx: Context,
    midi_quant: str = None,
    trigger_quant: str = None,
    swing: float = None,
) -> str:
    """
    Adjust record/trigger quantization settings.

    Parameters (pass only what you want to change):
    - midi_quant: MIDI recording quantize grid — '1/4', '1/8', '1/8t',
                  '1/16', '1/16t', '1/32', or 'none'
    - trigger_quant: clip-launch quantize grid (same accepted values)
    - swing: 0.0..1.0 swing amount applied to MIDI recording

    Live's UI labels these as "Record Quantization", "Quantization Menu",
    and "Groove > Global Amount" respectively.
    """
    try:
        ableton = get_ableton_connection()
        params = {}
        if midi_quant is not None:
            params["midi_quant"] = midi_quant
        if trigger_quant is not None:
            params["trigger_quant"] = trigger_quant
        if swing is not None:
            params["swing"] = float(swing)
        if not params:
            return "Error: provide at least one of midi_quant/trigger_quant/swing"
        result = ableton.send_command("set_record_quantization", params)
        return f"Record quantization changed: {result.get('changed')}"
    except Exception as e:
        logger.error(f"Error setting record quantization: {e}")
        return f"Error setting record quantization: {e}"


@mcp.tool()
def set_time_signature(
    ctx: Context,
    numerator: int,
    denominator: int,
) -> str:
    """
    Set the global time signature.

    Parameters:
    - numerator: 1..99 (typically 3, 4, 6, 7, 12)
    - denominator: must be 1, 2, 4, 8, or 16
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_time_signature", {
            "numerator": numerator,
            "denominator": denominator,
        })
        return (f"Time signature = "
                f"{result.get('signature_numerator')}/"
                f"{result.get('signature_denominator')}")
    except Exception as e:
        logger.error(f"Error setting time signature: {e}")
        return f"Error setting time signature: {e}"


@mcp.tool()
def set_session_record(
    ctx: Context,
    session_record: bool = None,
    arrangement_overdub: bool = None,
    back_to_arranger: bool = None,
) -> str:
    """
    Toggle session/arrangement record state.

    Parameters (pass only what you want to change):
    - session_record: arms the global session-record overdub
    - arrangement_overdub: enables arrangement-view overdub on playback
    - back_to_arranger: jumps arrangement playhead back to arranger position
    """
    try:
        ableton = get_ableton_connection()
        params = {}
        if session_record is not None:
            params["session_record"] = bool(session_record)
        if arrangement_overdub is not None:
            params["arrangement_overdub"] = bool(arrangement_overdub)
        if back_to_arranger is not None:
            params["back_to_arranger"] = bool(back_to_arranger)
        if not params:
            return ("Error: provide at least one of session_record / "
                    "arrangement_overdub / back_to_arranger")
        result = ableton.send_command("set_session_record", params)
        return f"Session/arrangement record changed: {result.get('changed')}"
    except Exception as e:
        logger.error(f"Error setting session record: {e}")
        return f"Error setting session record: {e}"


@mcp.tool()
def set_punch_region(
    ctx: Context,
    punch_in: bool = None,
    punch_out: bool = None,
) -> str:
    """
    Toggle arrangement-record punch-in / punch-out markers.

    PRECONDITION (Live 12.3.7): Live silently drops these writes unless
    `Song.loop = True` (arrangement loop button engaged). Enable the
    arrangement loop first via the Live UI, then call this. Response
    includes a `warning` field if the write didn't stick.

    Parameters (pass only what you want to change):
    - punch_in: enable/disable punch-in
    - punch_out: enable/disable punch-out
    """
    try:
        ableton = get_ableton_connection()
        params = {}
        if punch_in is not None:
            params["punch_in"] = bool(punch_in)
        if punch_out is not None:
            params["punch_out"] = bool(punch_out)
        if not params:
            return "Error: provide at least one of punch_in / punch_out"
        result = ableton.send_command("set_punch_region", params)
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting punch region: {e}")
        return f"Error setting punch region: {e}"


@mcp.tool()
def create_arrangement_clip_from_session(
    ctx: Context,
    track_index: int,
    source_clip_slot: int,
    start_beat: float,
    length_beats: float = None,
) -> str:
    """
    Place a session-view clip directly onto the arrangement timeline at
    start_beat — no record/playback needed. Bar-precise placement.

    Use when Live is open + you want to build/edit arrangement view
    programmatically without the lossy session→arrangement record dance.

    For MIDI source clips: notes are copied from the session clip into a new
    arrangement MIDI clip (via Track.create_midi_clip + set_notes).
    For audio source clips: the new arrangement clip references the same
    underlying sample file (via Track.create_audio_clip).

    Parameters:
    - track_index: target track (same track that contains the source clip)
    - source_clip_slot: index of the session clip slot to copy from
    - start_beat: arrangement timeline position (0 = song start)
    - length_beats: target arrangement clip length. If omitted, uses
                    source clip's length. For MIDI, notes are placed once
                    (no internal loop). For audio, Live's loop semantics apply.
    """
    try:
        ableton = get_ableton_connection()
        params = {
            "track_index": track_index,
            "source_clip_slot": source_clip_slot,
            "start_beat": start_beat,
        }
        if length_beats is not None:
            params["length_beats"] = length_beats
        result = ableton.send_command("create_arrangement_clip_from_session", params)
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error creating arrangement clip: {e}")
        return f"Error creating arrangement clip: {e}"


@mcp.tool()
def snap_clip_to_scale(
    ctx: Context,
    track_index: int,
    clip_index: int,
    root_note: int,
    scale_name: str = "Minor",
    strategy: str = "nearest",
) -> str:
    """
    Pitch-snap every note in a MIDI clip to the target scale.

    Scales: Major / Minor / Natural Minor / Harmonic Minor / Melodic Minor /
            Dorian / Phrygian / Lydian / Mixolydian / Locrian /
            Pentatonic Major / Pentatonic Minor / Blues / Chromatic.

    Parameters:
    - track_index, clip_index: target MIDI clip (session view)
    - root_note: 0 (C) .. 11 (B) — same convention as Live's Song.root_note
    - scale_name: see list above
    - strategy: 'nearest' (default, ties up) | 'up' | 'down'
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("snap_clip_to_scale", {
            "track_index": track_index,
            "clip_index": clip_index,
            "root_note": int(root_note),
            "scale_name": scale_name,
            "strategy": strategy,
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error snapping clip to scale: {e}")
        return f"Error snapping clip to scale: {e}"


@mcp.tool()
def shape_clip_velocities(
    ctx: Context,
    track_index: int,
    clip_index: int,
    curve: str = "linear",
    min_velocity: int = 20,
    max_velocity: int = 110,
) -> str:
    """
    Apply a velocity curve across a MIDI clip's notes (based on each note's
    start_time fraction within the clip).

    Curves:
    - linear:           ramp min → max
    - exp:              slow start, fast end (t²)
    - inv_exp:          fast start, slow end
    - soft_loud_soft:   bell curve, peak at clip midpoint
    - loud_soft_loud:   inverse bell, dip at midpoint
    - flat:             midpoint of (min, max) for all notes
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("shape_clip_velocities", {
            "track_index": track_index,
            "clip_index": clip_index,
            "curve": curve,
            "min_velocity": int(min_velocity),
            "max_velocity": int(max_velocity),
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error shaping velocities: {e}")
        return f"Error shaping velocities: {e}"


@mcp.tool()
def set_cue_point_name(ctx: Context, cue_index: int, name: str) -> str:
    """
    Rename a cue point in Song.cue_points by index. Use get_cue_points first
    to find indices.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_cue_point_name", {
            "cue_index": int(cue_index),
            "name": str(name),
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting cue point name: {e}")
        return f"Error setting cue point name: {e}"


@mcp.tool()
def get_arrangement_loop(ctx: Context) -> str:
    """
    Read the arrangement loop region: {loop_enabled, loop_start, loop_length}.
    Pair with set_arrangement_loop for the write side (already exists).
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_arrangement_loop", {})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error reading arrangement loop: {e}")
        return f"Error reading arrangement loop: {e}"


@mcp.tool()
def get_device_input_routings(ctx: Context, track_index: int, device_index: int) -> str:
    """
    List available and current input routing for a sidechain-capable device
    (Compressor with S/C, External Instrument, etc.).

    Use to discover valid source-track names before calling
    `set_device_input_routing`. Errors on devices without input routing.

    Returns: {device_name, available_input_types, current_input_type,
              available_input_channels, current_input_channel}.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_device_input_routings", {
            "track_index": track_index,
            "device_index": device_index,
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting device input routing: {e}")
        return f"Error getting device input routing: {e}"


@mcp.tool()
def set_device_input_routing(
    ctx: Context,
    track_index: int,
    device_index: int,
    type_display_name: str = None,
    channel_display_name: str = None,
) -> str:
    """
    Set a device's sidechain input source (e.g. Compressor S/C "Audio From"
    dropdown) by display name.

    For Compressor: type_display_name picks the SOURCE TRACK (typically
    "1-Drums" or similar), channel_display_name picks Pre/Post FX or a
    specific output channel.

    Use `get_device_input_routings` first to see valid options. Match is
    exact first, then case-insensitive substring fallback.

    Parameters:
    - track_index: track containing the device
    - device_index: device index on that track
    - type_display_name: source track / routing type name (e.g. "1-Drums")
    - channel_display_name: channel within source (e.g. "Post FX")
    """
    try:
        ableton = get_ableton_connection()
        params = {"track_index": track_index, "device_index": device_index}
        if type_display_name is not None:
            params["type_display_name"] = type_display_name
        if channel_display_name is not None:
            params["channel_display_name"] = channel_display_name
        if "type_display_name" not in params and "channel_display_name" not in params:
            return "Error: provide at least one of type_display_name / channel_display_name"
        result = ableton.send_command("set_device_input_routing", params)
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting device input routing: {e}")
        return f"Error setting device input routing: {e}"


@mcp.tool()
def set_arrangement_clip_position(
    ctx: Context,
    track_index: int,
    clip_index: int,
    new_start_beat: float = None,
    new_length: float = None,
) -> str:
    """
    Move and/or resize an existing arrangement clip in place.

    Pair this with `get_arrangement_clips` to locate the clip's position-in-tuple,
    and `create_arrangement_clip_from_session` for fresh placements. Together
    these unlock most arrangement-view editing while Live is open (without the
    session→arrangement record dance).

    Parameters:
    - track_index: index of the track holding the arrangement clip
    - clip_index: position in track.arrangement_clips (from get_arrangement_clips)
    - new_start_beat: target arrangement timeline start (omit to keep current)
    - new_length: target clip length in beats (omit to keep current)

    Implementation order: resize first, then move — avoids spurious overlap
    rejections from Live. Returns the post-write start/end/length.
    """
    try:
        ableton = get_ableton_connection()
        params = {"track_index": track_index, "clip_index": clip_index}
        if new_start_beat is not None:
            params["new_start_beat"] = new_start_beat
        if new_length is not None:
            params["new_length"] = new_length
        if "new_start_beat" not in params and "new_length" not in params:
            return "Error: provide at least one of new_start_beat / new_length"
        result = ableton.send_command("set_arrangement_clip_position", params)
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting arrangement clip position: {e}")
        return f"Error setting arrangement clip position: {e}"


@mcp.tool()
def set_record_mode(ctx: Context, enabled: bool) -> str:
    """
    Toggle Live's global arrangement record button (Song.record_mode).

    When True + playback is started, Live captures session-view clip
    firings onto the arrangement timeline (the standard
    session→arrangement record workflow).

    Parameters:
    - enabled: True to arm arrangement record, False to disable
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_record_mode", {"enabled": bool(enabled)})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting record_mode: {e}")
        return f"Error setting record_mode: {e}"


@mcp.tool()
def tap_tempo(ctx: Context) -> str:
    """
    Send a single tap event to Live's tap-tempo system.

    Call repeatedly on the beat to set tempo from taps (4+ taps typically
    needed for Live to lock to the tapped tempo).
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("tap_tempo", {})
        return (f"Tap. Tempo: {result.get('tempo_before'):.2f} → "
                f"{result.get('tempo_after'):.2f}")
    except Exception as e:
        logger.error(f"Error tap_tempo: {e}")
        return f"Error tap_tempo: {e}"


@mcp.tool()
def bump_tempo(ctx: Context, delta_bpm: float = 0.1) -> str:
    """
    Permanently adjust Song.tempo by a fixed BPM delta.

    NOT to be confused with Live's `nudge_up`/`nudge_down` properties —
    those are DJ-style temporary pitch-sync nudges (active only while
    a button is held). This tool writes Song.tempo directly for a
    permanent change, equivalent to clicking the ◀/▶ arrows in Live's
    transport bar.

    Parameters:
    - delta_bpm: signed delta. e.g. 0.1, -0.1, 1.0, -10.0
                 Result is clamped to Live's tempo range [20, 999].
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("bump_tempo", {"delta_bpm": float(delta_bpm)})
        return (f"Tempo {result.get('tempo_before'):.2f} → "
                f"{result.get('tempo_after'):.2f} "
                f"(delta {result.get('delta_bpm'):+.2f}"
                f"{', clamped' if result.get('clamped') else ''})")
    except Exception as e:
        logger.error(f"Error bump_tempo: {e}")
        return f"Error bump_tempo: {e}"


# ============================================================================
# Scenes batch (2026-05-17): scene CRUD, capture, props, fire
# ============================================================================


@mcp.tool()
def get_scenes(ctx: Context) -> str:
    """
    List all scenes with their metadata.

    Returns each scene's: index, name, color, color_index, tempo override,
    time signature override, is_triggered, is_empty.

    Scene-level tempo / time-signature overrides (Live 11+) trigger when
    the scene fires — useful for per-scene tempo automation in live sets.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_scenes", {})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error reading scenes: {e}")
        return f"Error reading scenes: {e}"


@mcp.tool()
def create_scene(ctx: Context, index: int = -1) -> str:
    """
    Create a new (empty) scene at the given 0-based index.

    Parameters:
    - index: insertion position. -1 appends at the end (default).
             Values from 0..len(scenes) inclusive are valid.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_scene", {"index": index})
        return (f"Created scene at index {result.get('scene_index')}: "
                f"'{result.get('name')}'. Total scenes now: {result.get('total_scenes')}")
    except Exception as e:
        logger.error(f"Error creating scene: {e}")
        return f"Error creating scene: {e}"


@mcp.tool()
def delete_scene(ctx: Context, scene_index: int) -> str:
    """
    Delete a scene by 0-based index.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("delete_scene", {"scene_index": scene_index})
        return (f"Deleted scene[{scene_index}] '{result.get('deleted_name')}'. "
                f"Total scenes now: {result.get('total_scenes')}")
    except Exception as e:
        logger.error(f"Error deleting scene: {e}")
        return f"Error deleting scene: {e}"


@mcp.tool()
def duplicate_scene(ctx: Context, scene_index: int) -> str:
    """
    Duplicate a scene. The copy is inserted immediately after the source.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("duplicate_scene", {"scene_index": scene_index})
        return (f"Duplicated scene[{result.get('source_index')}] → "
                f"new scene[{result.get('new_index')}] '{result.get('new_name')}'. "
                f"Total: {result.get('total_scenes')}")
    except Exception as e:
        logger.error(f"Error duplicating scene: {e}")
        return f"Error duplicating scene: {e}"


@mcp.tool()
def capture_and_insert_scene(ctx: Context) -> str:
    """
    Capture currently-playing clips into a new scene, inserted after the
    selected scene (Song.capture_and_insert_scene).

    No-op if nothing is playing. Useful for live-set design — jam-perform
    a combination of clips, then snapshot it as a scene.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("capture_and_insert_scene", {})
        if result.get("captured"):
            return (f"Captured currently-playing clips into new scene(s). "
                    f"Total scenes now: {result.get('total_scenes')}")
        return f"No scene created: {result.get('reason')}"
    except Exception as e:
        logger.error(f"Error capture_and_insert_scene: {e}")
        return f"Error capture_and_insert_scene: {e}"


@mcp.tool()
def set_scene_props(
    ctx: Context,
    scene_index: int,
    name: str = None,
    color: int = None,
    color_index: int = None,
    tempo: float = None,
    signature_numerator: int = None,
    signature_denominator: int = None,
) -> str:
    """
    Set scene properties. Pass only fields you want to change.

    Parameters:
    - name: scene name
    - color: RGB int (e.g. 0xFF8800 for orange)
    - color_index: 0..69 from Live's standard palette
    - tempo: float BPM override; pass -1.0 to clear the override
    - signature_numerator / signature_denominator: time signature override
      (-1 to clear; denominator must be 1/2/4/8/16)

    Tempo and time-signature overrides trigger automatically when the
    scene is fired.
    """
    try:
        ableton = get_ableton_connection()
        params = {"scene_index": scene_index}
        for k, v in (("name", name), ("color", color), ("color_index", color_index),
                     ("tempo", tempo),
                     ("signature_numerator", signature_numerator),
                     ("signature_denominator", signature_denominator)):
            if v is not None:
                params[k] = v
        if len(params) == 1:
            return "Error: provide at least one field to change"
        result = ableton.send_command("set_scene_props", params)
        return f"Scene[{scene_index}] changed: {result.get('changed')}"
    except Exception as e:
        logger.error(f"Error setting scene props: {e}")
        return f"Error setting scene props: {e}"


@mcp.tool()
def fire_scene(ctx: Context, scene_index: int) -> str:
    """
    Fire (trigger) a scene — launches all clips in that row.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("fire_scene", {"scene_index": scene_index})
        return f"Fired scene[{scene_index}] '{result.get('name')}'"
    except Exception as e:
        logger.error(f"Error firing scene: {e}")
        return f"Error firing scene: {e}"


# ============================================================================
# Track-state extras (2026-05-17): monitoring, freeze, color, fold, routings
# ============================================================================


@mcp.tool()
def set_track_monitoring(ctx: Context, track_index: int, mode: str) -> str:
    """
    Set a track's input monitoring mode (Track.current_monitoring_state).

    Parameters:
    - mode: "in" (always monitor — useful for live processing),
            "auto" (Live's default — monitor only when armed/playing),
            "off" (never monitor)

    Errors on tracks that don't support monitoring (master, returns).
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_monitoring", {
            "track_index": track_index,
            "mode": mode,
        })
        return (f"Track[{track_index}] '{result.get('name')}' "
                f"monitoring = {result.get('monitoring')}")
    except Exception as e:
        logger.error(f"Error setting track monitoring: {e}")
        return f"Error setting track monitoring: {e}"


@mcp.tool()
def set_track_freeze(ctx: Context, track_index: int, freeze: bool) -> str:
    """
    Freeze or unfreeze a track (CPU offload via bouncing to audio in place).

    LIVE API LIMITATION (Live 12.3.7, verified 2026-05-17):
    `Track.freeze()`/`Track.unfreeze()` methods are NOT exposed in this
    Live version's LOM despite Live 11 API docs claiming they exist.
    Only the read-only `is_frozen` property is available. Tool raises
    NotImplementedError with guidance to use Live's right-click menu.

    Parameters:
    - freeze: True = freeze, False = unfreeze (input validated but call
              will raise due to LOM limit)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_freeze", {
            "track_index": track_index,
            "freeze": bool(freeze),
        })
        return (f"Track[{track_index}] '{result.get('name')}' "
                f"action={result.get('action')}, is_frozen={result.get('is_frozen')}")
    except Exception as e:
        logger.error(f"Error setting track freeze: {e}")
        return f"Error setting track freeze: {e}"


@mcp.tool()
def set_track_color(
    ctx: Context,
    track_index: int,
    color: int = None,
    color_index: int = None,
) -> str:
    """
    Set a track's color via RGB int or Live's palette index.

    Parameters (provide at least one):
    - color: full RGB int (e.g. 0xFF8800 for orange)
    - color_index: 0..69 from Live's standard color palette
    """
    try:
        ableton = get_ableton_connection()
        params = {"track_index": track_index}
        if color is not None:
            params["color"] = int(color)
        if color_index is not None:
            params["color_index"] = int(color_index)
        if len(params) == 1:
            return "Error: provide color (RGB int) or color_index (0..69)"
        result = ableton.send_command("set_track_color", params)
        return (f"Track[{track_index}] '{result.get('name')}' "
                f"color changed: {result.get('changed')}")
    except Exception as e:
        logger.error(f"Error setting track color: {e}")
        return f"Error setting track color: {e}"


@mcp.tool()
def set_track_fold(ctx: Context, track_index: int, fold_state: bool) -> str:
    """
    Collapse or expand a group track (Track.fold_state).

    Only works on group tracks (is_foldable=True). Errors otherwise.

    Parameters:
    - fold_state: True to collapse the group, False to expand
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_fold", {
            "track_index": track_index,
            "fold_state": bool(fold_state),
        })
        return (f"Track[{track_index}] '{result.get('name')}' "
                f"fold_state={result.get('fold_state')}")
    except Exception as e:
        logger.error(f"Error setting track fold: {e}")
        return f"Error setting track fold: {e}"


@mcp.tool()
def get_available_routings(ctx: Context, track_index: int) -> str:
    """
    Read the available input/output routing types + channels for a track.

    Closes the discovery gap before calling set_track_routing — you need
    to know what's available to route to. Returns:
    - available_input_routing_types / channels
    - available_output_routing_types / channels
    - current_input_routing_type / current_output_routing_type

    Each routing type entry has display_name, category, and (when set)
    attached_object (e.g. another Track's name for sends).
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_available_routings",
                                       {"track_index": track_index})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting available routings: {e}")
        return f"Error getting available routings: {e}"


# ============================================================================
# Clip details batch (2026-05-17): color, gain, pitch, launch settings,
# follow actions
# ============================================================================


@mcp.tool()
def get_clip_settings(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Read a clip's full settings: color, gain (audio), pitch (audio),
    launch mode/quantization/legato/looping, follow action (Live 11+).

    Use to inspect current state before changing anything.

    Launch modes: 0=Trigger, 1=Gate, 2=Toggle, 3=Repeat
    Launch quantizations: 0=Global, 1=None, 2=8 Bars, 3=4 Bars, 4=2 Bars,
                          5=1 Bar, 6=1/2, 7=1/2T, 8=1/4, 9=1/4T, 10=1/8,
                          11=1/8T, 12=1/16, 13=1/16T, 14=1/32
    Follow actions: 0=No Action, 1=Stop, 2=Play Again, 3=Previous,
                    4=Next, 5=First, 6=Last, 7=Any, 8=Other
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_clip_settings", {
            "track_index": track_index,
            "clip_index": clip_index,
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error reading clip settings: {e}")
        return f"Error reading clip settings: {e}"


@mcp.tool()
def set_clip_color(
    ctx: Context,
    track_index: int,
    clip_index: int,
    color: int = None,
    color_index: int = None,
) -> str:
    """
    Set clip color via RGB int or Live's palette index.

    Parameters (provide at least one):
    - color: RGB int (e.g. 0xFF8800)
    - color_index: 0..69
    """
    try:
        ableton = get_ableton_connection()
        params = {"track_index": track_index, "clip_index": clip_index}
        if color is not None:
            params["color"] = int(color)
        if color_index is not None:
            params["color_index"] = int(color_index)
        if len(params) == 2:
            return "Error: provide color or color_index"
        result = ableton.send_command("set_clip_color", params)
        return f"Clip '{result.get('name')}' color changed: {result.get('changed')}"
    except Exception as e:
        logger.error(f"Error setting clip color: {e}")
        return f"Error setting clip color: {e}"


@mcp.tool()
def set_clip_gain(
    ctx: Context,
    track_index: int,
    clip_index: int,
    gain: float,
) -> str:
    """
    Set an audio clip's gain (Clip.gain). Audio clips only.

    Parameters:
    - gain: normalized 0.0..1.0 (Live's internal scale; 0.5 is unity).
            Clamped to range.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_gain", {
            "track_index": track_index,
            "clip_index": clip_index,
            "gain": float(gain),
        })
        return f"Clip '{result.get('name')}' gain = {result.get('gain'):.3f}"
    except Exception as e:
        logger.error(f"Error setting clip gain: {e}")
        return f"Error setting clip gain: {e}"


@mcp.tool()
def set_clip_pitch(
    ctx: Context,
    track_index: int,
    clip_index: int,
    coarse: int = None,
    fine: int = None,
) -> str:
    """
    Set an audio clip's pitch (Clip.pitch_coarse + pitch_fine). Audio only.

    Parameters (provide at least one):
    - coarse: -48..+48 semitones
    - fine: -50..+50 cents
    """
    try:
        ableton = get_ableton_connection()
        params = {"track_index": track_index, "clip_index": clip_index}
        if coarse is not None:
            params["coarse"] = int(coarse)
        if fine is not None:
            params["fine"] = int(fine)
        if len(params) == 2:
            return "Error: provide coarse (semitones) or fine (cents)"
        result = ableton.send_command("set_clip_pitch", params)
        return f"Clip '{result.get('name')}' pitch changed: {result.get('changed')}"
    except Exception as e:
        logger.error(f"Error setting clip pitch: {e}")
        return f"Error setting clip pitch: {e}"


@mcp.tool()
def set_clip_launch_settings(
    ctx: Context,
    track_index: int,
    clip_index: int,
    launch_mode: str = None,
    launch_quantization: str = None,
    legato: bool = None,
    looping: bool = None,
) -> str:
    """
    Set clip launch behavior (session view).

    Parameters (provide what you want to change):
    - launch_mode: "Trigger" / "Gate" / "Toggle" / "Repeat" (or int 0-3)
    - launch_quantization: "Global" / "None" / "8 Bars" / ... / "1/32"
                           (or int 0-14; see get_clip_settings for full list)
    - legato: True = launch from playing-clip position; False = restart
    - looping: True = loop on launch; False = one-shot

    These determine how clips respond to session-view triggers.
    """
    try:
        ableton = get_ableton_connection()
        params = {"track_index": track_index, "clip_index": clip_index}
        if launch_mode is not None:
            params["launch_mode"] = launch_mode
        if launch_quantization is not None:
            params["launch_quantization"] = launch_quantization
        if legato is not None:
            params["legato"] = bool(legato)
        if looping is not None:
            params["looping"] = bool(looping)
        if len(params) == 2:
            return "Error: provide at least one launch setting"
        result = ableton.send_command("set_clip_launch_settings", params)
        return f"Clip '{result.get('name')}' launch settings changed: {result.get('changed')}"
    except Exception as e:
        logger.error(f"Error setting clip launch settings: {e}")
        return f"Error setting clip launch settings: {e}"


@mcp.tool()
def set_clip_follow_action(
    ctx: Context,
    track_index: int,
    clip_index: int,
    enabled: bool = None,
    action_a: str = None,
    action_b: str = None,
    chance_a: int = None,
    chance_b: int = None,
    time_beats: float = None,
) -> str:
    """
    Configure follow action on a clip.

    LIVE API LIMITATION (Live 12.3.7, verified 2026-05-17): follow
    action properties are NOT exposed on Clip via the LOM. Despite
    being a Live 11+ user-facing feature, no Remote Script in
    AbletonLive12_MIDIRemoteScripts references the API. Tool raises
    NotImplementedError. Configure follow actions manually in Live's
    clip view.

    Parameters (provide what you want to change):
    - enabled: True/False (master switch)
    - action_a / action_b: one of "No Action", "Stop", "Play Again",
                           "Previous", "Next", "First", "Last",
                           "Any", "Other" (or int 0-8)
    - chance_a / chance_b: 0..127 weight for choosing this action
    - time_beats: how long the clip plays before the action fires

    Example: launch B (the next clip) every 8 beats unless A (replay) wins
      enabled=True, action_a="Play Again", action_b="Next",
      chance_a=50, chance_b=50, time_beats=8.0
    """
    try:
        ableton = get_ableton_connection()
        params = {"track_index": track_index, "clip_index": clip_index}
        if enabled is not None:
            params["enabled"] = bool(enabled)
        if action_a is not None:
            params["action_a"] = action_a
        if action_b is not None:
            params["action_b"] = action_b
        if chance_a is not None:
            params["chance_a"] = int(chance_a)
        if chance_b is not None:
            params["chance_b"] = int(chance_b)
        if time_beats is not None:
            params["time_beats"] = float(time_beats)
        if len(params) == 2:
            return "Error: provide at least one follow-action field"
        result = ableton.send_command("set_clip_follow_action", params)
        return f"Clip '{result.get('name')}' follow action changed: {result.get('changed')}"
    except Exception as e:
        logger.error(f"Error setting clip follow action: {e}")
        return f"Error setting clip follow action: {e}"


# ============================================================================
# Warp markers batch (2026-05-17): get / add / remove / move
# ============================================================================


@mcp.tool()
def get_warp_markers(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    List all warp markers on an audio clip.

    Each marker has:
    - beat_time: position in clip time (beats)
    - sample_time: position in the source audio (sample frames)

    Warp markers control how Live time-stretches the clip. Adding more
    markers gives finer time-feel control; moving them reshapes timing.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_warp_markers", {
            "track_index": track_index,
            "clip_index": clip_index,
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error reading warp markers: {e}")
        return f"Error reading warp markers: {e}"


@mcp.tool()
def add_warp_marker(
    ctx: Context,
    track_index: int,
    clip_index: int,
    beat_time: float,
    sample_time: float,
) -> str:
    """
    Add a warp marker at the given (beat_time, sample_time) position.

    Parameters:
    - beat_time: position in clip time (beats)
    - sample_time: position in the source audio (sample frames)

    Pair beat_time and sample_time to anchor a specific sample-time to
    a specific clip-time. Useful for nailing transients to grid positions.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("add_warp_marker", {
            "track_index": track_index,
            "clip_index": clip_index,
            "beat_time": float(beat_time),
            "sample_time": float(sample_time),
        })
        return (f"Added warp marker at beat_time={beat_time}, "
                f"sample_time={sample_time}. "
                f"Markers: {result.get('markers_before')} → {result.get('markers_after')}")
    except Exception as e:
        logger.error(f"Error adding warp marker: {e}")
        return f"Error adding warp marker: {e}"


@mcp.tool()
def remove_warp_marker(
    ctx: Context,
    track_index: int,
    clip_index: int,
    beat_time: float,
) -> str:
    """
    Remove the warp marker at the given beat_time.

    Errors silently (no-op) if no marker exists at that position.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("remove_warp_marker", {
            "track_index": track_index,
            "clip_index": clip_index,
            "beat_time": float(beat_time),
        })
        return (f"Remove at beat_time={beat_time}: "
                f"removed={result.get('removed')}, "
                f"markers: {result.get('markers_before')} → {result.get('markers_after')}")
    except Exception as e:
        logger.error(f"Error removing warp marker: {e}")
        return f"Error removing warp marker: {e}"


@mcp.tool()
def move_warp_marker(
    ctx: Context,
    track_index: int,
    clip_index: int,
    beat_time: float,
    new_beat_time: float,
) -> str:
    """
    Move the warp marker at beat_time to new_beat_time.

    The marker's sample_time stays anchored to the same audio position,
    but its clip-time position shifts — effectively stretching or
    compressing the audio between this marker and its neighbors.

    Tool accepts an absolute new_beat_time but Live's underlying API uses
    a delta; we convert automatically. Verified 2026-05-17.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("move_warp_marker", {
            "track_index": track_index,
            "clip_index": clip_index,
            "beat_time": float(beat_time),
            "new_beat_time": float(new_beat_time),
        })
        return (f"Moved warp marker {beat_time} → {new_beat_time}")
    except Exception as e:
        logger.error(f"Error moving warp marker: {e}")
        return f"Error moving warp marker: {e}"


# ----------------------------------------------------------------------
# Option-A batch (2026-06-01): 11 tools across 6 LOM families surfaced
# by the AbletonLive12_MIDIRemoteScripts survey workflow.
# ----------------------------------------------------------------------

@mcp.tool()
def duplicate_arrangement_clip(
    ctx: Context,
    track_index: int,
    source_arrangement_clip_index: int,
    destination_time: float,
) -> str:
    """
    Clone an arrangement-view clip at a new beat position on the same track
    via Live's Track.duplicate_clip_to_arrangement(clip, beat).

    Lossless alternative to delete+recreate — Live copies the source clip's
    content, warp markers, automation, and envelopes wholesale. This is
    THE correct path for arrangement-clip mutation (the older delete+recreate
    pattern in set_arrangement_clip_position is lossy on audio clips).

    Parameters:
    - track_index: 0-based track index (source + destination on same track).
    - source_arrangement_clip_index: index into track.arrangement_clips.
    - destination_time: target start time in beats (0 = song start).

    Returns the new clip's resolved index in track.arrangement_clips (via
    object-identity diff before/after — guaranteed unique even with same
    name/start-time collisions).
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("duplicate_arrangement_clip", {
            "track_index": track_index,
            "source_arrangement_clip_index": source_arrangement_clip_index,
            "destination_time": float(destination_time),
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error duplicating arrangement clip: {e}")
        return f"Error duplicating arrangement clip: {e}"


@mcp.tool()
def begin_undo_step(ctx: Context) -> str:
    """
    Open an undo-history boundary so the next batch of edits coalesces
    into a single undoable step.

    CRITICAL: caller MUST pair with end_undo_step before returning control
    to the user. An unbalanced begin leaves the undo stack OPEN, so the
    user's NEXT manual edit will get folded into the script's undo step —
    Cmd-Z then undoes both the script batch AND the user's last manual
    action.

    Use before any multi-step write batch (Tier 2 layered apply, arrangement
    build, bulk note edits) so one Cmd-Z restores the prior state.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("begin_undo_step", {})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error begin_undo_step: {e}")
        return f"Error begin_undo_step: {e}"


@mcp.tool()
def end_undo_step(ctx: Context) -> str:
    """
    Close the undo-history boundary opened by begin_undo_step.

    Always call after a batch of writes that opened a boundary, so the
    user's subsequent manual edits get their own undo step (instead of
    being folded into the script's batch).
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("end_undo_step", {})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error end_undo_step: {e}")
        return f"Error end_undo_step: {e}"


@mcp.tool()
def get_focused_view(ctx: Context) -> str:
    """
    Read Application.View.focused_document_view + visibility of the main
    panels.

    On Live 12.3.7, focused_document_view returns ONE of: 'Session',
    'Arranger' (these are the two main document views — auxiliary panels
    like Browser/Detail don't take document focus). The returned visibility
    map reports show/hide state for Browser, Arranger, Session, Detail,
    Detail/Clip, Detail/DeviceChain.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_focused_view", {})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error get_focused_view: {e}")
        return f"Error get_focused_view: {e}"


@mcp.tool()
def set_focused_view(ctx: Context, view_name: str) -> str:
    """
    Bring a Live document view to the front via Application.View.show_view(name).

    Valid view_name values (canonical from view_control.py):
      'Browser', 'Arranger', 'Session', 'Detail',
      'Detail/Clip', 'Detail/DeviceChain'.

    Note: the canonical name is 'Arranger' (NOT 'Arrangement'). The common
    'Arrangement' misspelling is auto-corrected for convenience; the
    response includes 'auto_corrected': True when this happens.

    The 'focused_view' field in the response reflects only the main document
    panel (Session/Arranger) — not auxiliary panels like Browser or Detail.
    Use the 'is_visible' field to confirm whether the requested view was
    actually shown.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_focused_view", {
            "view_name": view_name,
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error set_focused_view: {e}")
        return f"Error set_focused_view: {e}"


@mcp.tool()
def set_view_visible(ctx: Context, view_name: str, visible: bool) -> str:
    """
    Show or hide a named document view via Application.View.show_view
    or hide_view.

    Parameters:
    - view_name: same canonical names as set_focused_view.
    - visible: True to show, False to hide.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_view_visible", {
            "view_name": view_name,
            "visible": bool(visible),
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error set_view_visible: {e}")
        return f"Error set_view_visible: {e}"


@mcp.tool()
def get_clip_playing_state(
    ctx: Context,
    track_index: int,
    clip_index: int,
    location: str = "session",
) -> str:
    """
    Read live playback state for a clip: playing_position, is_playing,
    is_triggered, is_recording, plus length/loop region.

    Parameters:
    - track_index: 0-based.
    - clip_index: session slot index (location='session') OR
                  arrangement_clips index (location='arrangement').
    - location: 'session' (default) or 'arrangement'.

    Returns {has_clip: False, ...} for empty session slots / out-of-range
    arrangement_clips index — poll callers shouldn't have to wrap every
    call in try/except just because the user emptied a slot mid-poll.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_clip_playing_state", {
            "track_index": track_index,
            "clip_index": clip_index,
            "location": location,
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error get_clip_playing_state: {e}")
        return f"Error get_clip_playing_state: {e}"


@mcp.tool()
def get_track_playback_state(ctx: Context, track_index: int) -> str:
    """
    Read Track-level session playback indices:
      - fired_slot_index: -2 = "stop clip pending", -1 = nothing fired,
                          >=0 = slot whose clip is queued.
      - playing_slot_index: >=0 = slot of currently-playing clip, <0 none.
      - is_playing: Track-level audio activity.

    Use to discover which session clip is currently playing on a track
    without polling each clip_slot's is_triggered/is_playing.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_track_playback_state", {
            "track_index": track_index,
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error get_track_playback_state: {e}")
        return f"Error get_track_playback_state: {e}"


@mcp.tool()
def delete_notes_in_range(
    ctx: Context,
    track_index: int,
    clip_index: int,
    from_time: float,
    time_span: float,
    from_pitch: int = 0,
    pitch_span: int = 128,
    location: str = "session",
) -> str:
    """
    Delete every MIDI note inside a (time, pitch) rectangle via
    Clip.remove_notes_extended.

    Defaults nuke ALL pitches (from_pitch=0, pitch_span=128) in the
    given time range — the same idiom Live's own components use for
    whole-page clears. Pass narrower from_pitch/pitch_span to scope.

    Parameters:
    - track_index: 0-based.
    - clip_index: session slot OR arrangement_clips index.
    - from_time: start beat of the rectangle.
    - time_span: beat-width (must be > 0).
    - from_pitch: lowest MIDI pitch to clear (0..127, default 0).
    - pitch_span: semitones to clear (default 128 = all). from_pitch +
                  pitch_span must be <= 128.
    - location: 'session' (default) or 'arrangement'.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("delete_notes_in_range", {
            "track_index": track_index,
            "clip_index": clip_index,
            "from_time": float(from_time),
            "time_span": float(time_span),
            "from_pitch": int(from_pitch),
            "pitch_span": int(pitch_span),
            "location": location,
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error delete_notes_in_range: {e}")
        return f"Error delete_notes_in_range: {e}"


@mcp.tool()
def delete_notes_with_pitch(
    ctx: Context,
    track_index: int,
    clip_index: int,
    pitch: int,
    from_time: float = 0.0,
    time_span: float = None,
    location: str = "session",
) -> str:
    """
    Delete every note at a single MIDI pitch from a clip. Convenience
    over delete_notes_in_range with pitch_span=1.

    Parameters:
    - track_index: 0-based.
    - clip_index: session slot OR arrangement_clips index.
    - pitch: MIDI pitch 0..127 (e.g. 36 = C1 kick).
    - from_time: start beat (default 0).
    - time_span: beat-width (omit / None = full clip length).
    - location: 'session' (default) or 'arrangement'.
    """
    try:
        ableton = get_ableton_connection()
        params = {
            "track_index": track_index,
            "clip_index": clip_index,
            "pitch": int(pitch),
            "from_time": float(from_time),
            "location": location,
        }
        if time_span is not None:
            params["time_span"] = float(time_span)
        result = ableton.send_command("delete_notes_with_pitch", params)
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error delete_notes_with_pitch: {e}")
        return f"Error delete_notes_with_pitch: {e}"


@mcp.tool()
def duplicate_clip_loop(
    ctx: Context,
    track_index: int,
    clip_index: int,
    location: str = "session",
) -> str:
    """
    Doubles the looped region of a clip in place via Clip.duplicate_loop().

    Live copies content from [loop_start, loop_end) to
    [loop_end, 2*loop_end - loop_start) and extends loop_end + end_marker
    accordingly. Pre-checks Clip.looping == True; raises if loop mode
    is off.

    WARNING: if duplicating would exceed Live's max clip length, Live may
    surface a UI dialog that blocks the Remote Script main thread → the
    call times out at 15s. Pre-check old_length for very long clips.

    Parameters:
    - track_index: 0-based.
    - clip_index: session slot OR arrangement_clips index.
    - location: 'session' (default) or 'arrangement'.

    Returns old/new length + loop region for verification.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("duplicate_clip_loop", {
            "track_index": track_index,
            "clip_index": clip_index,
            "location": location,
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error duplicate_clip_loop: {e}")
        return f"Error duplicate_clip_loop: {e}"


# Main execution
def main():
    """Run the MCP server"""
    mcp.run()

if __name__ == "__main__":
    main()