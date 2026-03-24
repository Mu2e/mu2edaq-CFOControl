"""
ots_mm_udp_interface.py

Python reimplementation of ots_mm_udp_interface (C++) for communicating with
the otsdaq MacroMaker supervisor over UDP.  Supports both IPv4 and IPv6.

Protocol overview:
  - All messages are UTF-8 text, semicolon-delimited
  - Responses are XML fragments, potentially split across multiple UDP packets
  - Special characters in command/argument values are percent-encoded (URI encoding)
  - Initial receive timeout: 10 s; inter-packet timeout: 0.2 s
  - Max UDP payload: 5000 bytes
"""

import select
import socket
from typing import List, Optional, Tuple

MAXBUFLEN = 5000
TIMEOUT_FIRST_PACKET = 10.0   # seconds – wait for first response packet
TIMEOUT_NEXT_PACKET  = 0.2    # seconds – wait for subsequent packets


# ---------------------------------------------------------------------------
# Encoding helpers
# ---------------------------------------------------------------------------

def encode_uri_component(data: str) -> str:
    """Percent-encode all non-alphanumeric characters (mirrors JS encodeURIComponent)."""
    result = []
    for ch in data:
        if ch.isalpha() or ch.isdigit():
            result.append(ch)
        else:
            for byte in ch.encode("utf-8"):
                result.append(f"%{byte:02X}")
    return "".join(result)


def decode_uri_component(data: str) -> str:
    """Decode percent-encoded sequences back to Unicode text."""
    result = []
    i = 0
    while i < len(data):
        if data[i] == "%" and i + 2 < len(data):
            hex_str = data[i + 1 : i + 3]
            try:
                result.append(chr(int(hex_str, 16)))
                i += 3
                continue
            except ValueError:
                pass
        result.append(data[i])
        i += 1
    return "".join(result)


def decode_html_entities(data: str) -> str:
    """Replace common HTML entities with their character equivalents."""
    _TABLE = {
        "&lt;":   "<",
        "&gt;":   ">",
        "&amp;":  "&",
        "&quot;": '"',
        "&apos;": "'",
        "&#160;": " ",
        "&#013;": "\n",
    }
    for entity, char in _TABLE.items():
        data = data.replace(entity, char)
    return data


# ---------------------------------------------------------------------------
# XML field extractor
# ---------------------------------------------------------------------------

def extract_xml_field(
    xml: str,
    field: str,
    occurrence: int = 0,
    after: int = 0,
) -> Tuple[str, int]:
    """
    Find the ``occurrence``-th (0-based) instance of ``<field value='...'/>``
    starting at position ``after`` in ``xml``.

    Returns (value, position_after_tag).  On failure returns ("", -1).
    """
    search = f"<{field} value='"
    pos = after
    found = 0
    while True:
        idx = xml.find(search, pos)
        if idx == -1:
            return "", -1
        if found == occurrence:
            start = idx + len(search)
            end = xml.find("'/>", start)
            if end == -1:
                return "", -1
            return xml[start:end], end + 3
        found += 1
        pos = idx + len(search)


# ---------------------------------------------------------------------------
# UDP socket helpers
# ---------------------------------------------------------------------------

def _make_socket(host: str, port: int) -> Tuple[socket.socket, tuple]:
    """
    Resolve *host* (IPv4 or IPv6 address / hostname) and create a non-blocking
    UDP socket.  Returns (socket, destination_address).
    """
    infos = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_DGRAM)
    if not infos:
        raise RuntimeError(f"Cannot resolve host: {host!r}")
    af, socktype, proto, _canon, dest_addr = infos[0]
    sock = socket.socket(af, socktype, proto)
    sock.setblocking(False)
    return sock, dest_addr


def _receive(
    sock: socket.socket,
    timeout: float,
) -> Optional[bytes]:
    """Wait up to *timeout* seconds for a UDP packet; return None on timeout."""
    ready, _, _ = select.select([sock], [], [], timeout)
    if ready:
        data, _ = sock.recvfrom(MAXBUFLEN)
        return data
    return None


# ---------------------------------------------------------------------------
# Main interface class
# ---------------------------------------------------------------------------

class OtsMMUdpInterface:
    """
    Communicate with an otsdaq MacroMaker supervisor over UDP.

    Parameters
    ----------
    host : str
        IPv4 address, IPv6 address, or hostname of the MacroMaker.
    port : int
        UDP port the MacroMaker is listening on.
    timeout_first : float
        Seconds to wait for the first response packet (default 10 s).
    timeout_next : float
        Seconds to wait for each subsequent packet (default 0.2 s).
    verbose : bool
        Print raw send/receive traffic to stdout.
    """

    def __init__(
        self,
        host: str,
        port: int,
        timeout_first: float = TIMEOUT_FIRST_PACKET,
        timeout_next: float = TIMEOUT_NEXT_PACKET,
        verbose: bool = False,
    ) -> None:
        self._host = host
        self._port = port
        self._timeout_first = timeout_first
        self._timeout_next = timeout_next
        self._verbose = verbose
        self._full_xml: str = ""

        self._sock, self._dest_addr = _make_socket(host, port)

    # ------------------------------------------------------------------
    # Low-level send / receive
    # ------------------------------------------------------------------

    def _send(self, message: str) -> None:
        encoded = message.encode("utf-8")
        if self._verbose:
            print(f"[SEND] {message}")
        self._sock.sendto(encoded, self._dest_addr)

    def _receive_all(self) -> str:
        """Receive all UDP packets for one logical response."""
        chunks: List[str] = []
        first = True
        while True:
            timeout = self._timeout_first if first else self._timeout_next
            first = False
            data = _receive(self._sock, timeout)
            if data is None:
                break
            chunk = data.decode("utf-8", errors="replace")
            if self._verbose:
                print(f"[RECV {len(data)}B] {chunk[:200]}")
            chunks.append(chunk)
        return "".join(chunks)

    # ------------------------------------------------------------------
    # Frontend macro info (cached)
    # ------------------------------------------------------------------

    def get_frontend_macro_info(self, force_refresh: bool = False) -> str:
        """
        Query the MacroMaker for information about all front-end macros and
        cache the XML response.  Subsequent calls return the cached value
        unless *force_refresh* is True.
        """
        if self._full_xml and not force_refresh:
            return self._full_xml

        self._send("GetFrontendMacroInfo")
        xml = self._receive_all()

        if not xml:
            raise RuntimeError(
                "Empty response to GetFrontendMacroInfo – "
                "check that the MacroMaker supervisor is running and reachable."
            )

        self._full_xml = xml
        return self._full_xml

    # ------------------------------------------------------------------
    # Internal: parse FEMacros fields for a specific frontend
    # ------------------------------------------------------------------

    def _get_all_fe_entries(self) -> List[List[str]]:
        """Return every FEMacros entry as a list of stripped fields."""
        xml = self.get_frontend_macro_info()
        entries: List[List[str]] = []
        pos = 0
        while True:
            value, next_pos = extract_xml_field(xml, "FEMacros", after=pos)
            if next_pos == -1:
                break
            entries.append([f.strip() for f in value.split(";")])
            pos = next_pos
        return entries

    def _get_fe_fields(self, target_fe: str) -> List[str]:
        """Return the semicolon-split fields for *target_fe* or raise."""
        xml = self.get_frontend_macro_info()
        pos = 0
        while True:
            value, next_pos = extract_xml_field(xml, "FEMacros", after=pos)
            if next_pos == -1:
                raise RuntimeError(
                    f"Frontend UID {target_fe!r} not found.  "
                    "Use get_frontend_list() to see available frontends."
                )
            fields = [f.strip() for f in value.split(";")]
            # field[3] is the interface UID
            if len(fields) > 3 and fields[3] == target_fe:
                return fields
            pos = next_pos

    @staticmethod
    def _iter_commands(fields: List[str]):
        """
        Yield (command_name_encoded, cmd_idx, num_inputs, num_outputs_idx) for
        every macro entry in *fields* (starting at index 4).
        """
        i = 4  # skip: supervisor_name, supervisor_lid, interface_type, interface_uid
        while i < len(fields):
            if not fields[i]:
                i += 1
                continue
            cmd_name = fields[i]
            # fields[i+1] = permissions, fields[i+2] = tooltip, fields[i+3] = num_inputs
            if i + 3 >= len(fields):
                break
            raw_num_in = fields[i + 3].strip()
            if not raw_num_in.lstrip("-").isdigit():
                break
            num_inputs = int(raw_num_in)
            num_outputs_idx = i + 4 + num_inputs
            if num_outputs_idx >= len(fields):
                break
            raw_num_out = fields[num_outputs_idx].strip()
            if not raw_num_out.lstrip("-").isdigit():
                break
            num_outputs = int(raw_num_out)
            yield cmd_name, i, num_inputs, num_outputs_idx, num_outputs
            i = num_outputs_idx + 1 + num_outputs

    def _find_command(self, target_fe: str, command: str):
        """
        Return (fields, cmd_idx, num_inputs, num_outputs_idx, num_outputs)
        for *command* on *target_fe*, or raise RuntimeError.
        """
        fields = self._get_fe_fields(target_fe)
        for cmd_enc, cmd_idx, num_inputs, num_outputs_idx, num_outputs in self._iter_commands(fields):
            if decode_uri_component(cmd_enc) == command:
                return fields, cmd_idx, num_inputs, num_outputs_idx, num_outputs
        raise RuntimeError(
            f"Command {command!r} not found for frontend {target_fe!r}.  "
            "Use get_command_list() to see available commands."
        )

    # ------------------------------------------------------------------
    # Public query methods
    # ------------------------------------------------------------------

    def get_frontend_list(self) -> List[str]:
        """Return a list of all available front-end UIDs."""
        uids: List[str] = []
        for entry in self._get_all_fe_entries():
            if len(entry) > 3:
                uids.append(entry[3])
        return uids

    def get_command_list(self, target_fe: str) -> List[str]:
        """Return a list of all macro command names available for *target_fe*."""
        fields = self._get_fe_fields(target_fe)
        return [
            decode_uri_component(cmd_enc)
            for cmd_enc, *_ in self._iter_commands(fields)
        ]

    def get_command_input_count(self, target_fe: str, command: str) -> int:
        """Return the number of input parameters required by *command*."""
        _, _idx, num_inputs, *_ = self._find_command(target_fe, command)
        return num_inputs

    def get_command_output_count(self, target_fe: str, command: str) -> int:
        """Return the number of output values produced by *command*."""
        *_, num_outputs = self._find_command(target_fe, command)
        return num_outputs

    def get_command_input_name(self, target_fe: str, command: str, input_index: int) -> str:
        """Return the name of input parameter at *input_index* (0-based)."""
        fields, cmd_idx, num_inputs, *_ = self._find_command(target_fe, command)
        if input_index < 0 or input_index >= num_inputs:
            raise RuntimeError(
                f"Input index {input_index} out of range "
                f"(command {command!r} has {num_inputs} input(s))."
            )
        return decode_uri_component(fields[cmd_idx + 4 + input_index])

    def get_command_output_name(self, target_fe: str, command: str, output_index: int) -> str:
        """Return the name of output parameter at *output_index* (0-based)."""
        fields, _cmd_idx, _num_in, num_outputs_idx, num_outputs = self._find_command(
            target_fe, command
        )
        if output_index < 0 or output_index >= num_outputs:
            raise RuntimeError(
                f"Output index {output_index} out of range "
                f"(command {command!r} has {num_outputs} output(s))."
            )
        return decode_uri_component(fields[num_outputs_idx + 1 + output_index])

    # ------------------------------------------------------------------
    # Command execution
    # ------------------------------------------------------------------

    def run_command(
        self,
        target_fe: str,
        command: str,
        inputs: str = "",
    ) -> List[str]:
        """
        Execute *command* on *target_fe*.

        Parameters
        ----------
        target_fe : str
            Front-end UID (must match exactly).
        command : str
            Macro name (must match exactly).
        inputs : str
            Pre-encoded input string in the format expected by the MacroMaker:
            ``name1,value1;name2,value2;...`` where each name/value is already
            URI-encoded.  Use :func:`build_input_string` to construct this.

        Returns
        -------
        list of str
            URI-encoded output values, one per output parameter.
        """
        # Resolve fe_type from cached macro info
        xml = self.get_frontend_macro_info()
        fe_type = ""
        pos = 0
        while True:
            value, next_pos = extract_xml_field(xml, "FEMacros", after=pos)
            if next_pos == -1:
                raise RuntimeError(f"Frontend {target_fe!r} not found.")
            fields = [f.strip() for f in value.split(";")]
            if len(fields) > 3 and fields[3] == target_fe:
                fe_type = fields[2]
                break
            pos = next_pos

        # Build output names string
        num_outputs = self.get_command_output_count(target_fe, command)
        output_names = [
            self.get_command_output_name(target_fe, command, i)
            for i in range(num_outputs)
        ]
        encoded_outputs = encode_uri_component(",".join(output_names))

        # Build and send the message
        # Format: RunFrontendMacro;fe_type;target_fe;fe;cmd;inputs;outputs;save_flag
        message = ";".join([
            "RunFrontendMacro",
            fe_type,
            target_fe,
            "fe",
            encode_uri_component(command),
            inputs,
            encoded_outputs,
            "0",
        ])
        self._send(message)

        response = self._receive_all()
        if not response:
            raise RuntimeError(
                f"Empty response when executing command {command!r} "
                f"on frontend {target_fe!r}."
            )

        # Check for server-side errors
        err_val, err_pos = extract_xml_field(response, "Error")
        if err_pos != -1:
            raise RuntimeError(
                f"MacroMaker error: {decode_uri_component(err_val)}"
            )

        # Extract output values in order
        output_values: List[str] = []
        pos = 0
        while True:
            val, next_pos = extract_xml_field(response, "outputArgs_value", after=pos)
            if next_pos == -1:
                break
            output_values.append(val)
            pos = next_pos

        return output_values

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def build_input_string(
        self,
        target_fe: str,
        command: str,
        values: List[str],
    ) -> str:
        """
        Build the input string for :meth:`run_command` from a list of plain
        string values.  The names are fetched from the MacroMaker; values are
        URI-encoded automatically.

        Parameters
        ----------
        values : list of str
            Plain (non-encoded) input values in parameter order.
        """
        num_inputs = self.get_command_input_count(target_fe, command)
        if len(values) != num_inputs:
            raise RuntimeError(
                f"Command {command!r} expects {num_inputs} input(s), "
                f"got {len(values)}."
            )
        pairs = []
        for idx, val in enumerate(values):
            name = self.get_command_input_name(target_fe, command, idx)
            pairs.append(
                f"{encode_uri_component(name)},{encode_uri_component(val)}"
            )
        return ";".join(pairs)

    def decode_outputs(self, output_values: List[str]) -> List[str]:
        """URI-decode a list of raw output values returned by :meth:`run_command`."""
        return [decode_uri_component(v) for v in output_values]

    # ------------------------------------------------------------------
    # Context manager / cleanup
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying UDP socket."""
        if self._sock:
            self._sock.close()
            self._sock = None

    def __enter__(self) -> "OtsMMUdpInterface":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"OtsMMUdpInterface(host={self._host!r}, port={self._port})"
