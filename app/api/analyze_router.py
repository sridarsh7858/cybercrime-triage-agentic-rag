from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.concurrency import run_in_threadpool

from app.schemas.incident_schemas import AnalysisResponse
from app.services.agentic_rag_service import run_agentic_triage
from app.services.ocr_service import extract_text_from_image

router = APIRouter()

# EasyOCR decodes the whole image into memory, so an unbounded upload is an easy
# way to exhaust the process. 10 MB comfortably covers a phone screenshot.
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@router.post("/analyze", response_model=AnalysisResponse)
async def analyze_incident(
    query: str = Form(None, description="The user's text complaint"),
    file: UploadFile = File(None, description="Screenshot of the scam/fraud"),
):
    try:
        if not query and not file:
            raise HTTPException(
                status_code=400,
                detail="Must provide either a text 'query' or an image 'file'.",
            )

        # 1. OCR runs here. We keep the raw OCR text SEPARATE from the typed
        #    query so the graph's Node A can sanitize the UI noise itself,
        #    instead of us blindly concatenating noisy text into the prompt.
        ocr_text = ""
        if file:
            if file.content_type and not file.content_type.startswith("image/"):
                raise HTTPException(
                    status_code=415,
                    detail=f"Unsupported file type '{file.content_type}'. Upload an image.",
                )

            print(f"[analyze] Processing image: {file.filename}")
            image_bytes = await file.read()
            if len(image_bytes) > _MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"Image exceeds the {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
                )

            # EasyOCR is synchronous and CPU-bound; running it inline would stall
            # the event loop for every other request for the duration.
            try:
                ocr_text = await run_in_threadpool(extract_text_from_image, image_bytes)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))

        raw_query = (query or "").strip()

        # 2. Run the agentic LangGraph pipeline.
        print("[analyze] Invoking agentic RAG graph...")
        state = await run_agentic_triage(raw_query=raw_query, raw_ocr_text=ocr_text)

        # 3. Map the final graph state -> API response.
        output = state.get("generation_output") or {}
        kept_docs = state.get("retrieved_docs") or []

        return AnalysisResponse(
            query=state.get("cleaned_context") or raw_query,
            retrieved_context_count=len(kept_docs),
            threat_classification=output.get("threat_classification"),
            legal_category=output.get("legal_category"),
            consumer_mitigation_steps=output.get("consumer_mitigation_steps") or [],
            soc_investigation_playbook=output.get("soc_investigation_playbook") or [],
            confidence=output.get("confidence"),
            route_taken=state.get("route") or None,
            reasoning=output.get("reasoning"),
            incident_tags=state.get("incident_tags") or [],
        )

    except HTTPException:
        # Preserve intentional client errors (e.g. the 400 above) as-is
        raise
    except Exception as e:
        # Log the detail for the operator; hand the caller something generic so
        # internal paths and stack context do not leak out of the API.
        print(f"[analyze] unhandled error: {e!r}")
        raise HTTPException(
            status_code=500, detail="Triage failed. Check the server logs for details."
        )
