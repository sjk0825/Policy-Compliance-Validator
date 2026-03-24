from typing import Optional
from .base import BaseTool, ToolResult, ToolDefinition, ToolCapability


class FileTool(BaseTool):
    def __init__(self, extract_func=None):
        super().__init__()
        self._extract_func = extract_func

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="file_processor",
            description="PDF, 이미지, 텍스트 파일에서 텍스트를 추출합니다.",
            capabilities=[ToolCapability.FILE_PROCESSING],
            parameters={
                "required": ["file_bytes", "file_type"],
                "properties": {
                    "file_bytes": {"type": "string", "description": "파일 바이트 데이터 (base64)"},
                    "file_type": {"type": "string", "description": "파일 타입 (pdf, jpg, png, txt)"}
                }
            }
        )

    def execute(self, file_bytes: bytes, file_type: str) -> ToolResult:
        try:
            if self._extract_func:
                text = self._extract_func(file_bytes, file_type)
            else:
                text = self._default_extract(file_bytes, file_type)

            return ToolResult(
                success=True,
                data={"text": text, "char_count": len(text)},
                metadata={
                    "tool": "file_processor",
                    "action": "extract",
                    "file_type": file_type
                }
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    def _default_extract(self, file_bytes: bytes, file_type: str) -> str:
        if file_type == "txt":
            return file_bytes.decode("utf-8")
        elif file_type == "pdf":
            return self._extract_pdf(file_bytes)
        elif file_type in ["jpg", "jpeg", "png"]:
            return self._extract_image(file_bytes)
        else:
            raise ValueError(f"Unsupported file type: {file_type}")

    def _extract_pdf(self, file_bytes: bytes) -> str:
        from PyPDF2 import PdfReader
        import io
        reader = PdfReader(io.BytesIO(file_bytes))
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return text

    def _extract_image(self, file_bytes: bytes) -> str:
        from PIL import Image
        import pytesseract
        import io
        image = Image.open(io.BytesIO(file_bytes))
        return pytesseract.image_to_string(image, lang="kor+eng")
