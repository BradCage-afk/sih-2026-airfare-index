"""A tiny stand-in for NIM's /v1/chat/completions.

Lets the whole pipeline be tested — client, parsing, validation, retry,
chunking, writes — without spending NIM quota or needing a network. It reads
the fare rows out of the prompt and answers with the JSON a good model would
produce, and can be told to misbehave in the ways real models do.

    python tests/mock_nim.py --port 8848 --mode clean
"""
from __future__ import annotations

import argparse
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

ROW = re.compile(
    r"^(?P<carrier>[A-Za-z][A-Za-z .]+?)\s*\|\s*(?P<flight>[A-Z0-9]{2}-\d+)\s*\|\s*"
    r"(?P<dep>\d{1,2}:\d{2}).*?(?P<price>₹\s?[\d,]+)",
)


def flights_from_prompt(prompt: str) -> list[dict]:
    out = []
    for line in prompt.splitlines():
        m = ROW.match(line.strip())
        if not m:
            continue
        out.append({
            "carrier": m.group("carrier").strip(),
            "flight_number": m.group("flight"),
            "departure_time": m.group("dep"),
            "base_fare": None, "taxes": None, "udf": None, "convenience_fee": None,
            "total_fare": int(m.group("price").replace("₹", "").replace(",", "").strip()),
        })
    return out


class Handler(BaseHTTPRequestHandler):
    mode = "clean"
    calls = 0

    def log_message(self, *a):  # keep the test output clean
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        prompt = body["messages"][-1]["content"]
        Handler.calls += 1
        mode = Handler.mode

        if mode == "server_error" and Handler.calls == 1:
            self.send_error(500, "upstream on fire")
            return

        payload = json.dumps({"flights": flights_from_prompt(prompt)})
        if mode == "fenced":
            content = f"Here is the data:\n```json\n{payload}\n```"
        elif mode == "truncated" and "ONLY valid JSON" not in prompt:
            content = payload[: len(payload) // 2]        # cut mid-object
        elif mode == "garbage" :
            content = "I cannot help with that."
        else:
            content = payload

        out = json.dumps({
            "id": "chatcmpl-mock", "object": "chat.completion", "model": body["model"],
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": len(prompt) // 4, "completion_tokens": len(content) // 4},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


def serve(port: int = 8848, mode: str = "clean") -> tuple[HTTPServer, threading.Thread]:
    Handler.mode = mode
    Handler.calls = 0
    server = HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8848)
    ap.add_argument("--mode", default="clean",
                    choices=["clean", "fenced", "truncated", "garbage", "server_error"])
    args = ap.parse_args()
    server, _ = serve(args.port, args.mode)
    print(f"mock NIM on http://127.0.0.1:{args.port}/v1 (mode={args.mode})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
