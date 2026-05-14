from dataclasses import dataclass


@dataclass
class CloneConfig:
    max_depth: int = 10
    max_pages: int = 500
    concurrency: int = 10
    timeout: int = 30
    max_file_size: int = 50 * 1024 * 1024  # 50 MB
    user_agent: str = "StaticSiteCloner/1.0"
    output_dir: str = "output"
