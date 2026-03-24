#!/usr/bin/env python3
"""
CFOControl.py – Command-line interface for the otsdaq MacroMaker UDP interface.

Python reimplementation of ots_mm_udp_test (C++) with YAML configuration
support and IPv4/IPv6 compatibility.

Usage examples
--------------
List all frontends:
    python CFOControl.py

List commands for a specific frontend:
    python CFOControl.py --fe CFO0

Run a command with arguments:
    python CFOControl.py --fe CFO0 --cmd "Check Firefly Loss-of-Light"

Run a command with explicit input values:
    python CFOControl.py --fe CFO0 --cmd "SetRegister" --inputs "0x9100" "0x1"

Use a custom config file:
    python CFOControl.py --config my_config.yaml --fe CFO0

Override connection from the command line:
    python CFOControl.py --host 192.168.1.10 --port 5000 --fe CFO0

Refresh the cached frontend macro info before running:
    python CFOControl.py --fe CFO0 --cmd "SomeCmd" --refresh
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import List, Optional

try:
    import yaml
except ImportError:
    sys.exit(
        "PyYAML is required: pip install pyyaml"
    )

from ots_mm_udp_interface import (
    OtsMMUdpInterface,
    decode_uri_component,
    encode_uri_component,
)

# ---------------------------------------------------------------------------
# Default configuration (matches config.yaml structure)
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "connection": {
        "host": "127.0.0.1",
        "port": 5000,
    },
    "timeouts": {
        "first_packet": 10.0,
        "next_packet": 0.2,
    },
    "logging": {
        "level": "INFO",
        "verbose_udp": False,
    },
}

logger = logging.getLogger("CFOControl")


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_config(path: Optional[str]) -> dict:
    """
    Load YAML configuration, falling back to defaults for missing keys.
    If *path* is None, look for ``config.yaml`` next to this script.
    """
    config = _deep_merge({}, DEFAULT_CONFIG)

    search_paths: List[Path] = []
    if path:
        search_paths.append(Path(path))
    else:
        search_paths.append(Path(__file__).parent / "config.yaml")

    for p in search_paths:
        if p.exists():
            with p.open() as fh:
                user_cfg = yaml.safe_load(fh) or {}
            config = _deep_merge(config, user_cfg)
            logger.debug("Loaded config from %s", p)
            break
    else:
        if path:
            sys.exit(f"Config file not found: {path}")
        logger.debug("No config.yaml found; using built-in defaults.")

    return config


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base* (returns a new dict)."""
    result = dict(base)
    for key, val in override.items():
        if isinstance(val, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="CFOControl",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Connection (override config file)
    conn = p.add_argument_group("connection overrides")
    conn.add_argument(
        "--host",
        metavar="HOST",
        help="IPv4 address, IPv6 address, or hostname of the MacroMaker "
             "(overrides config file)",
    )
    conn.add_argument(
        "--port",
        type=int,
        metavar="PORT",
        help="UDP port of the MacroMaker (overrides config file)",
    )

    # Config file
    p.add_argument(
        "--config",
        metavar="FILE",
        help="Path to YAML configuration file (default: config.yaml next to this script)",
    )

    # Operation modes
    p.add_argument(
        "--fe", "--frontend",
        dest="frontend",
        metavar="FE_UID",
        help="Front-end UID to target.  Omit to list all available front-ends.",
    )
    p.add_argument(
        "--cmd", "--command",
        dest="command",
        metavar="COMMAND",
        help="Macro command to run.  Omit to list commands for --fe.",
    )
    p.add_argument(
        "--inputs",
        nargs="*",
        metavar="VALUE",
        default=None,
        help="Input argument values in parameter order.  "
             "Must match the number of inputs expected by --cmd.",
    )

    # Misc
    p.add_argument(
        "--refresh",
        action="store_true",
        help="Force a fresh query of frontend macro info (ignore cache).",
    )
    p.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print raw UDP send/receive traffic.",
    )
    p.add_argument(
        "--list-inputs",
        action="store_true",
        help="List input parameter names for --fe / --cmd and exit.",
    )
    p.add_argument(
        "--list-outputs",
        action="store_true",
        help="List output parameter names for --fe / --cmd and exit.",
    )

    return p


# ---------------------------------------------------------------------------
# Mode implementations
# ---------------------------------------------------------------------------

def mode_list_frontends(iface: OtsMMUdpInterface) -> int:
    """Print all available front-end UIDs."""
    fe_list = iface.get_frontend_list()
    if not fe_list:
        print("No front-ends reported by the MacroMaker.")
        return 1
    print(f"Available front-ends ({len(fe_list)}):")
    for uid in fe_list:
        print(f"  {uid}")
    return 0


def mode_list_commands(iface: OtsMMUdpInterface, fe: str) -> int:
    """Print all commands available for a given front-end."""
    cmd_list = iface.get_command_list(fe)
    if not cmd_list:
        print(f"No commands found for front-end {fe!r}.")
        return 1
    print(f"Commands for {fe!r} ({len(cmd_list)}):")
    for cmd in cmd_list:
        n_in  = iface.get_command_input_count(fe, cmd)
        n_out = iface.get_command_output_count(fe, cmd)
        print(f"  {cmd}  (inputs: {n_in}, outputs: {n_out})")
    return 0


def mode_list_parameters(
    iface: OtsMMUdpInterface,
    fe: str,
    command: str,
    show_inputs: bool,
    show_outputs: bool,
) -> int:
    """Print input and/or output parameter names for a command."""
    if show_inputs:
        n = iface.get_command_input_count(fe, command)
        print(f"Inputs for {fe!r} / {command!r} ({n}):")
        for i in range(n):
            print(f"  [{i}] {iface.get_command_input_name(fe, command, i)}")

    if show_outputs:
        n = iface.get_command_output_count(fe, command)
        print(f"Outputs for {fe!r} / {command!r} ({n}):")
        for i in range(n):
            print(f"  [{i}] {iface.get_command_output_name(fe, command, i)}")

    return 0


def mode_run_command(
    iface: OtsMMUdpInterface,
    fe: str,
    command: str,
    input_values: Optional[List[str]],
) -> int:
    """Execute a command and print the decoded output values."""
    n_inputs  = iface.get_command_input_count(fe, command)
    n_outputs = iface.get_command_output_count(fe, command)

    # Validate / default inputs
    if input_values is None:
        input_values = []

    if len(input_values) != n_inputs:
        print(
            f"Error: command {command!r} expects {n_inputs} input(s), "
            f"got {len(input_values)}.",
            file=sys.stderr,
        )
        if n_inputs > 0:
            print("Expected input parameters:", file=sys.stderr)
            for i in range(n_inputs):
                name = iface.get_command_input_name(fe, command, i)
                print(f"  [{i}] {name}", file=sys.stderr)
        return 1

    # Build input string
    input_str = iface.build_input_string(fe, command, input_values)

    logger.debug(
        "Running %r on %r  inputs=%r  encoded=%r",
        command, fe, input_values, input_str,
    )

    raw_outputs = iface.run_command(fe, command, input_str)

    if len(raw_outputs) != n_outputs:
        logger.warning(
            "Expected %d output(s) but received %d.", n_outputs, len(raw_outputs)
        )

    print(f"Output from {fe!r} / {command!r}:")
    for i, raw in enumerate(raw_outputs):
        name  = iface.get_command_output_name(fe, command, i) if i < n_outputs else f"output[{i}]"
        value = decode_uri_component(raw)
        print(f"  {name}: {value}")

    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args   = parser.parse_args(argv)

    # --- Configure logging ---
    config = load_config(args.config)
    log_level = getattr(logging, config["logging"]["level"].upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(levelname)s: %(message)s",
    )
    if args.verbose:
        config["logging"]["verbose_udp"] = True

    # --- Apply CLI overrides to config ---
    if args.host:
        config["connection"]["host"] = args.host
    if args.port:
        config["connection"]["port"] = args.port

    host    = config["connection"]["host"]
    port    = config["connection"]["port"]
    t_first = config["timeouts"]["first_packet"]
    t_next  = config["timeouts"]["next_packet"]
    verbose = config["logging"]["verbose_udp"]

    logger.debug("Connecting to %s:%d", host, port)

    try:
        with OtsMMUdpInterface(
            host=host,
            port=port,
            timeout_first=t_first,
            timeout_next=t_next,
            verbose=verbose,
        ) as iface:

            # Force cache refresh if requested
            if args.refresh:
                iface.get_frontend_macro_info(force_refresh=True)

            # --- Mode: list front-ends ---
            if args.frontend is None:
                return mode_list_frontends(iface)

            fe = args.frontend

            # --- Mode: list parameter names ---
            if args.list_inputs or args.list_outputs:
                if args.command is None:
                    parser.error("--list-inputs / --list-outputs require --cmd")
                return mode_list_parameters(
                    iface, fe, args.command,
                    show_inputs=args.list_inputs,
                    show_outputs=args.list_outputs,
                )

            # --- Mode: list commands for FE ---
            if args.command is None:
                return mode_list_commands(iface, fe)

            # --- Mode: run command ---
            return mode_run_command(iface, fe, args.command, args.inputs)

    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
