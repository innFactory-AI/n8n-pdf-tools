"""AcroForm fields: list, fill, flatten."""

import io
from typing import Any

import pikepdf
import pypdf
from pypdf.generic import NameObject

from ..doc import Doc
from ..errors import PdfToolError

FIELD_TYPES = {"/Tx": "text", "/Btn": "button", "/Ch": "choice", "/Sig": "signature"}


def _states(field: dict[str, Any]) -> list[str]:
    states = field.get("/_States_", [])
    return [str(s).lstrip("/") for s in states if str(s) != "/Off"]


def list_fields(doc: Doc) -> list[dict[str, Any]]:
    reader = pypdf.PdfReader(io.BytesIO(doc.snapshot()))
    fields = reader.get_fields() or {}
    result = []
    for name, field in fields.items():
        kind = FIELD_TYPES.get(str(field.get("/FT", "")), "unknown")
        flags = int(field.get("/Ff", 0) or 0)
        if kind == "button":
            kind = "radio" if flags & (1 << 15) else "pushbutton" if flags & (1 << 16) else "checkbox"
        value = field.get("/V")
        entry: dict[str, Any] = {
            "name": name,
            "type": kind,
            "value": None if value is None else str(value).lstrip("/") if kind in ("checkbox", "radio") else str(value),
            "required": bool(flags & 2),
            "read_only": bool(flags & 1),
        }
        if kind in ("checkbox", "radio"):
            entry["states"] = _states(field)
        if kind == "choice" and field.get("/Opt"):
            entry["options"] = [str(o[1] if isinstance(o, list) else o) for o in field["/Opt"]]
        result.append(entry)
    return result


def _normalize(value: Any, field: dict[str, Any]) -> str:
    if field["type"] in ("checkbox", "radio"):
        states = field.get("states") or ["Yes"]
        if value is True or str(value).lower() in ("true", "yes", "on", "1", "x"):
            return f"/{states[0]}"
        if value is False or value is None or str(value).lower() in ("false", "no", "off", "0", ""):
            return "/Off"
        if str(value).lstrip("/") in states:
            return f"/{str(value).lstrip('/')}"
        raise PdfToolError(
            f"field '{field['name']}' accepts {states} or true/false, got '{value}'", "invalid_field_value"
        )
    return "" if value is None else str(value)


def fill(doc: Doc, values: dict[str, Any], flatten_after: bool = False, ignore_unknown: bool = False) -> None:
    known = {f["name"]: f for f in list_fields(doc)}
    if not known:
        raise PdfToolError("the PDF has no form fields", "no_form")
    unknown = sorted(set(values) - set(known))
    if unknown and not ignore_unknown:
        raise PdfToolError(f"unknown fields: {unknown} (set ignore_unknown=true to skip)", "unknown_fields")
    prepared = {k: _normalize(v, known[k]) for k, v in values.items() if k in known}

    writer = pypdf.PdfWriter(clone_from=pypdf.PdfReader(io.BytesIO(doc.snapshot())))
    for page in writer.pages:
        if page.get("/Annots"):
            writer.update_page_form_field_values(page, prepared, auto_regenerate=False)
    writer._root_object["/AcroForm"][NameObject("/NeedAppearances")] = pypdf.generic.BooleanObject(True)
    out = io.BytesIO()
    writer.write(out)
    doc.replace(out.getvalue())
    if flatten_after:
        flatten(doc, regenerate=False)  # pypdf just wrote fresh appearances


def _regenerate_with_pypdf(doc: Doc) -> None:
    """Rewrite text/choice appearances from the current values (pypdf handles Unicode)."""
    current = {
        f["name"]: f["value"] for f in list_fields(doc) if f["type"] in ("text", "choice") and f["value"] is not None
    }
    if not current:
        return
    writer = pypdf.PdfWriter(clone_from=pypdf.PdfReader(io.BytesIO(doc.snapshot())))
    for page in writer.pages:
        if page.get("/Annots"):
            writer.update_page_form_field_values(page, current, auto_regenerate=False)
    out = io.BytesIO()
    writer.write(out)
    doc.replace(out.getvalue())


def flatten(doc: Doc, regenerate: bool | None = None) -> None:
    """Burn form fields and annotations into the page content; the result is no longer editable.

    Appearances are regenerated when the PDF asks for it (NeedAppearances, e.g. filled by
    another tool), by pypdf first because qpdf's generator falls back to '?' outside the
    font encoding. qpdf then only fills in widgets that still have no appearance.
    """
    acroform = doc.pdf.Root.get("/AcroForm")
    if regenerate is None:
        regenerate = acroform is not None and bool(acroform.get("/NeedAppearances", False))
    if regenerate:
        _regenerate_with_pypdf(doc)
    pdf = doc.pdf
    if "/AcroForm" in pdf.Root:
        missing = any(
            "/AP" not in annot
            for page in pdf.pages
            for annot in page.get("/Annots", [])
            if annot.get("/Subtype") == pikepdf.Name.Widget
        )
        pdf.Root.AcroForm.NeedAppearances = missing
        if missing:
            pdf.generate_appearance_streams()
    pdf.flatten_annotations("all")
    if "/AcroForm" in pdf.Root:
        del pdf.Root["/AcroForm"]
