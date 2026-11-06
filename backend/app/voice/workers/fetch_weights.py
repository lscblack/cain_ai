"""Downloads a model's weights. Run with the model environment's Python by the manager."""
from __future__ import annotations

import json
import os
import sys

from huggingface_hub import hf_hub_download, snapshot_download


def main() -> None:
    spec = json.loads(sys.argv[1])
    for item in spec["weights"]:
        target = os.path.join(spec["dir"], item["subdir"]) if item["subdir"] else spec["dir"]
        if item["filename"]:
            hf_hub_download(item["repo"], item["filename"], revision=item["revision"], local_dir=target)
        else:
            snapshot_download(item["repo"], revision=item["revision"], local_dir=target,
                              allow_patterns=list(item["patterns"]) or None)
    print("WEIGHTS_OK", flush=True)


if __name__ == "__main__":
    main()
