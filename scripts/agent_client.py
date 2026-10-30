"""Small local HTTP client for an external asset-production agent."""

import argparse
import base64
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import quote


def request(base_url, method, path, payload=None):
    headers = {"Accept": "application/json"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(base_url.rstrip("/") + "/api" + path, data, headers, method=method)
    with urlopen(req, timeout=60) as response:
        return json.load(response)


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:18765")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("health")
    bundle = commands.add_parser("bundle")
    bundle.add_argument("task_id")
    bundle.add_argument("--output", type=Path)
    bundle.add_argument("--download-images", action="store_true", help="Save task images beside the output JSON")
    upload = commands.add_parser("upload")
    upload.add_argument("image", type=Path)
    submit = commands.add_parser("submit")
    submit.add_argument("task_id")
    submit.add_argument("result", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "health":
            result = request(args.url, "GET", "/health")
        elif args.command == "bundle":
            result = request(args.url, "GET", f"/tasks/{args.task_id}/bundle")
            if args.download_images:
                if not args.output:
                    raise ValueError("--download-images requires --output")
                image_dir = args.output.parent / (args.output.stem + "-images")
                image_dir.mkdir(parents=True, exist_ok=True)
                for index, image in enumerate(result.get("images", [])):
                    image_id = quote(str(image["id"]), safe="")
                    with urlopen(args.url.rstrip("/") + "/api/images/" + image_id, timeout=60) as response:
                        image_path = image_dir / f"image-{index + 1:03d}.png"
                        image_path.write_bytes(response.read())
                        image["local_file"] = str(image_path.resolve())
        elif args.command == "upload":
            if args.image.stat().st_size > 20 * 1024 * 1024:
                raise ValueError("Image exceeds the 20 MiB upload limit")
            result = request(args.url, "POST", "/images", {
                "filename": args.image.name,
                "data_base64": base64.b64encode(args.image.read_bytes()).decode("ascii"),
            })
        else:
            result = request(args.url, "POST", f"/tasks/{args.task_id}/result", json.loads(args.result.read_text(encoding="utf-8-sig")))
        output = json.dumps(result, ensure_ascii=False, indent=2)
        if args.command == "bundle" and args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output + "\n", encoding="utf-8")
            print(f"Saved task bundle: {args.output.resolve()}")
        else:
            print(output)
        return 0
    except HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}", file=sys.stderr)
    except (URLError, OSError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
