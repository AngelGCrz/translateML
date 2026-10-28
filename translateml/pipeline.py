"""Pasos compartidos por los comandos: cargar un manifest con su plantilla y generar un idioma."""
from __future__ import annotations

from pathlib import Path as FilePath
from typing import Dict, List, Optional, Tuple

from .config import ConfigError, Language, Settings, load_languages
from .export import ManifestError, load_manifest, units_from_manifest, write_json
from .jsonpath import format_path
from .extraction import Profile, TextUnit, load_profiles, select_profile
from .rebuild import rebuild
from .template import Template, load_template
from .validation import validate_output


def load_manifest_template(manifest_file: FilePath, settings: Settings):
    """Manifest, plantilla (sin cambios desde la extracción), perfil y unidades."""
    manifest = load_manifest(manifest_file)
    template = load_template(manifest["template"]["file"])
    if template.sha256 != manifest["template"]["sha256"]:
        raise ManifestError("La plantilla cambió desde la extracción. Ejecuta 'extract' de nuevo.")
    profile = select_profile(template.data, load_profiles(settings.profiles_dir), manifest["profile"])
    return manifest, template, profile, units_from_manifest(manifest)


def enabled_language(settings: Settings, code: Optional[str]) -> Language:
    languages = load_languages(settings.languages_file)
    language = languages.get(code or languages.source)
    if not language.enabled:
        raise ConfigError(f"El idioma {language.code} no está habilitado en languages.json.")
    return language


def build_language(template: Template, profile: Profile, units: List[TextUnit], texts: Dict[str, str],
                   language: Language, settings: Settings, out: FilePath, quiet: bool = False,
                   merges: Optional[Dict[str, List[str]]] = None) -> Tuple[int, Dict]:
    """Reconstruye, valida y escribe <out>/<carpeta del idioma>/info.json con su informe.

    Devuelve (código de salida, informe). Con `quiet` no se lista cada incidencia por pantalla.
    """
    result = rebuild(template, units, texts, profile, merges)
    errors = validate_output(template, result.text, result.changes, result.removals)
    target = out / language.folder / settings.output_filename
    report = {
        "language": language.code, "output": str(target), "changed_texts": len(result.changes),
        "kept_source": len(result.missing), "validation_errors": errors,
        "merged_lines": [format_path(p) for p in result.removals],
        "issues": [vars(i) for i in result.issues], "written": False,
    }
    blocked = settings.missing_translation_policy == "error" and result.missing
    for issue in [] if quiet else result.issues:
        print(f"  {'!' if issue.blocking else '~'} {issue.key} {issue.path}: {issue.kind} - {issue.detail}")
    if errors or blocked:
        for error in errors:
            print(f"  ERROR {error}")
        write_json(out / f"rebuild-report-{language.code}.json", report)
        print(f"No se generó {target}. Revisa {out / f'rebuild-report-{language.code}.json'}.")
        return 1, report
    if target.resolve() == template.file.resolve():
        raise ManifestError("La salida coincide con la plantilla original; elige otra carpeta.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(template.encode(result.text))
    report["written"] = True
    write_json(out / f"rebuild-report-{language.code}.json", report)
    print(f"{language.code}: {len(result.changes)} textos cambiados, {len(result.missing)} conservados del original -> {target}")
    return 0, report
