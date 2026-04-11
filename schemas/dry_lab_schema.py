from pydantic import BaseModel
from typing import Optional, List


class ReproducibilityTarget(BaseModel):
    paper_title: str
    paper_source: str
    github_url: Optional[str] = None
    requirements_file: Optional[str] = None
    data_download_urls: List[str] = []
    main_script: Optional[str] = None
    expected_outputs: List[str] = []
    extraction_notes: List[str] = []
