"""Optional synthetic 20 MP per-process observation, not a capacity guarantee."""
import json
from pathlib import Path
import resource
import subprocess
import sys
import tempfile
import time

from PIL import Image


def main():
    if len(sys.argv) > 1:
        from app.photos.validation import decode_raster
        raw = Path(sys.argv[1]).read_bytes()
        start = time.monotonic()
        result = decode_raster(raw)
        print(json.dumps({"format": result.mime_type, "input_bytes": len(raw),
            "output_bytes": len(result.data), "pixels": result.width * result.height,
            "elapsed_seconds": round(time.monotonic() - start, 4),
            "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}))
        return
    results = []
    with tempfile.TemporaryDirectory(prefix="synthetic-photo-memory-") as directory:
        for fmt in ("PNG", "JPEG", "WEBP"):
            path = Path(directory) / (fmt.lower() + ".img")
            image = Image.new("RGB", (5000, 4000), (20, 80, 120))
            image.save(path, fmt)
            image.close()
            completed = subprocess.run([sys.executable, __file__, str(path)], capture_output=True,
                                       text=True, timeout=60, check=True)
            results.append(json.loads(completed.stdout))
    print(json.dumps({"synthetic_solid_color_only": True, "not_mixed_workload_capacity": True,
                      "observations": results}, indent=2))


if __name__ == "__main__":
    main()
