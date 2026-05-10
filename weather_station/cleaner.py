import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


class Cleaner:
    def __init__(self, delete_wav: bool = True, delete_png: bool = True):
        self.delete_wav = delete_wav
        self.delete_png = delete_png

    def cleanup(self, files: list[Path]) -> dict[str, int]:
        stats = {"wav": 0, "png": 0, "skipped": 0}
        for f in files:
            if not f.exists():
                continue
            suffix = f.suffix.lower()
            if suffix == ".wav" and self.delete_wav:
                f.unlink()
                logger.debug("Deleted: %s", f.name)
                stats["wav"] += 1
            elif suffix == ".png" and self.delete_png:
                f.unlink()
                logger.debug("Deleted: %s", f.name)
                stats["png"] += 1
            else:
                stats["skipped"] += 1
        if stats["wav"] or stats["png"]:
            logger.info("Cleaned up %d wav + %d png file(s)", stats["wav"], stats["png"])
        return stats

    def cleanup_old_files(self, directory: Path, max_age_hours: int = 48) -> int:
        if not directory.exists():
            return 0
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        count = 0
        for f in directory.iterdir():
            if f.is_file() and datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
                f.unlink()
                logger.info("Removed stale file: %s", f.name)
                count += 1
        return count
