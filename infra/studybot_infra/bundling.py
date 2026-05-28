from pathlib import Path
import shutil

import jsii
from aws_cdk import ILocalBundling


@jsii.implements(ILocalBundling)
class ReuseBackendBundle:
    def __init__(self, backend_src_path: str) -> None:
        self.backend_src_path = Path(backend_src_path)

    def try_bundle(self, output_dir: str, *_args, **_kwargs) -> bool:
        output_path = Path(output_dir)
        cdk_out = output_path.parent
        requirements = (self.backend_src_path / "requirements.txt").read_text(encoding="utf-8")
        candidates = [
            path
            for path in cdk_out.glob("asset.*")
            if path.is_dir()
            and not path.name.endswith("-building")
            and (path / "requirements.txt").exists()
            and (path / "requirements.txt").read_text(encoding="utf-8") == requirements
            and (path / "boto3").exists()
        ]
        if not candidates:
            return False
        candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        shutil.copytree(candidates[0], output_path, dirs_exist_ok=True)
        for source in self.backend_src_path.iterdir():
            target = output_path / source.name
            if source.name in {".env", "__pycache__"}:
                continue
            if source.is_dir():
                shutil.copytree(source, target, dirs_exist_ok=True)
            else:
                shutil.copy2(source, target)
        for pycache in output_path.rglob("__pycache__"):
            shutil.rmtree(pycache, ignore_errors=True)
        env_file = output_path / ".env"
        if env_file.exists():
            env_file.unlink()
        return True
