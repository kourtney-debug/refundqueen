def ocr_image_with_api(file_storage):
    """
    Takes the uploaded file, sends it to OCR.space, and returns extracted text.
    Also logs the full OCR response so we can see errors.
    """
    if not OCR_API_KEY:
        raise RuntimeError("OCR_API_KEY is not set")

    # Ensure we're at the start of the file
    file_storage.seek(0)
    file_bytes = file_storage.read()

    files = {"file": ("receipt.jpg", file_bytes, file_storage.mimetype or "image/jpeg")}
    data = {
        "apikey": OCR_API_KEY,
        "language": "eng",
        "OCREngine": 2,
    }

    try:
        # Using http to avoid SSL issues in this environment
        r = requests.post(
            "http://api.ocr.space/parse/image",
            files=files,
            data=data,
            timeout=60,
        )
        r.raise_for_status()
        result = r.json()
    except Exception as e:
        print("OCR API error:", e, flush=True)
        traceback.print_exc()
        return ""

    # 🔍 LOG THE FULL RAW OCR RESPONSE
    print("FULL OCR RESULT:", result, flush=True)

    # If the API says there was an error, log and return empty
    if result.get("IsErroredOnProcessing"):
        print("OCR ERROR MESSAGE:", result.get("ErrorMessage"), flush=True)
        print("OCR ERROR DETAILS:", result.get("ErrorDetails"), flush=True)
        return ""

    if not result.get("ParsedResults"):
        return ""

    return result["ParsedResults"][0].get("ParsedText", "")
