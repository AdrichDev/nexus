# -*- coding: utf-8 -*-
"""Regresión aislada para fallos de contenido vacío de Hermes.

No importa la skill ni configuración del host: extrae por AST solo el clasificador
puro y comprueba por estructura que el camino de admisión no maquilla respuestas
vacías como éxito.
"""
from __future__ import annotations

import ast
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
SKILL_PY = os.path.join(ROOT, "skills", "hermes", "skill.py")


class HermesEmptyResponseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(SKILL_PY, encoding="utf-8") as f:
            cls.source = f.read()
        cls.tree = ast.parse(cls.source, filename=SKILL_PY)
        ns = {"re": re}
        wanted = {"_RESPUESTA_ES_ERROR", "respuesta_es_error"}
        for node in cls.tree.body:
            names = {target.id for target in getattr(node, "targets", []) if isinstance(target, ast.Name)}
            if names & wanted or (isinstance(node, ast.FunctionDef) and node.name in wanted):
                exec(compile(ast.Module([node], []), SKILL_PY, "exec"), ns)
        cls.respuesta_es_error = staticmethod(ns["respuesta_es_error"])

    def test_provider_empty_content_warning_is_error(self):
        warning = (
            "⚠️ No reply: the model returned empty content after retries and any fallback providers. "
            "Try `continue`, switch model/provider, or inspect the tool output above."
        )
        motivo = self.respuesta_es_error(warning)
        self.assertTrue(motivo, "el aviso real de respuesta vacía no puede marcarse como éxito")
        self.assertIn("No reply", motivo)

    def test_empty_auth_and_quota_errors_remain_errors(self):
        self.assertTrue(self.respuesta_es_error(""))
        self.assertTrue(self.respuesta_es_error("Missing Authentication header"))
        self.assertTrue(self.respuesta_es_error("insufficient_quota: credits exhausted"))
        self.assertTrue(self.respuesta_es_error("HTTP 400: Your organization must be verified"))

    def test_successful_prose_about_empty_responses_is_not_rejected(self):
        ejemplos = [
            "Aquí tienes el informe de proveedores: tres opciones viables y próximos pasos.",
            "This note explains that empty responses can happen, but this answer has useful content.",
            "El diagnóstico menciona respuestas vacías del proveedor sin ser él mismo un fallo.",
        ]
        for texto in ejemplos:
            with self.subTest(texto=texto):
                self.assertEqual(self.respuesta_es_error(texto), "")

    def test_admission_path_does_not_replace_empty_content_before_classifying(self):
        run = next(
            node for node in self.tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_run_hermes"
        )
        masking_assignments = []
        for node in ast.walk(run):
            if not isinstance(node, ast.Assign):
                continue
            if not any(isinstance(t, ast.Name) and t.id == "out" for t in node.targets):
                continue
            value = node.value
            if isinstance(value, ast.BoolOp) and isinstance(value.op, ast.Or):
                masking_assignments.append(node.lineno)
        self.assertEqual(
            masking_assignments,
            [],
            "_run_hermes no debe convertir contenido vacío en texto de éxito antes del clasificador",
        )

        motivo_line = hecho_line = raise_after_motivo = None
        for node in ast.walk(run):
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "motivo" for t in node.targets):
                if isinstance(node.value, ast.Call) and getattr(node.value.func, "id", "") == "respuesta_es_error":
                    motivo_line = node.lineno
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_reg_set":
                for kw in node.keywords:
                    if kw.arg == "estado" and isinstance(kw.value, ast.Constant) and kw.value.value == "hecho":
                        hecho_line = node.lineno
            if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "motivo":
                if any(isinstance(child, ast.Raise) for child in ast.walk(node)):
                    raise_after_motivo = node.lineno
        self.assertIsNotNone(motivo_line, "_run_hermes debe llamar a respuesta_es_error(out)")
        self.assertIsNotNone(raise_after_motivo, "un motivo de error debe levantar RuntimeError")
        self.assertIsNotNone(hecho_line, "el camino de éxito debe seguir marcando hecho")
        self.assertLess(motivo_line, hecho_line, "Hermes debe clasificar el contenido antes de marcar hecho")
        self.assertLess(raise_after_motivo, hecho_line, "Hermes debe fallar antes de registrar éxito")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    unittest.main(verbosity=2)
