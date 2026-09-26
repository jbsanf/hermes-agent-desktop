from pathlib import Path
from PIL import Image

app = "io.github.jbsanf.HermesDesktop"
root = Path("/app/share/icons/hicolor")
original = root / f"1024x1024/apps/{app}.png"
with Image.open(original) as source:
    for size in (64, 128, 256, 512):
        target = root / f"{size}x{size}/apps/{app}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        source.resize((size, size), Image.Resampling.LANCZOS).save(target)
original.unlink()
