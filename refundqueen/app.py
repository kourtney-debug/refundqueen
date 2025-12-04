def ocr_image_with_api(file_storage):
    ...
    try:
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

    if not result.get("ParsedResults"):
        return ""

    return result["ParsedResults"][0].get("ParsedText", "")
