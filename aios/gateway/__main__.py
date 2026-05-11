"""
TaijiOS LLM Gateway — uvicorn entrypoint.

Usage:
    python -m aios.gateway [--host 127.0.0.1] [--port 9200]
    # or
    uvicorn aios.gateway.app:app --host 127.0.0.1 --port 9200
"""
import argparse
import os
import uvicorn


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(prog="python -m aios.gateway", description="Run TaijiOS LLM Gateway")
    parser.add_argument("--host", default=os.getenv("TAIJIOS_GATEWAY_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("TAIJIOS_GATEWAY_PORT", "9200")))
    parser.add_argument("--log-level", default=os.getenv("TAIJIOS_GATEWAY_LOG_LEVEL", "info"))
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    host = args.host
    port = args.port
    print(f"[gateway] Starting TaijiOS LLM Gateway on {host}:{port}")
    uvicorn.run("aios.gateway.app:app", host=host, port=port, log_level=args.log_level)


if __name__ == "__main__":
    main()
