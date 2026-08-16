from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from markus_mcp.tools.saga.documents.parse_facturi_xml import parse_facturi_xml
from markus_mcp.tools.saga.documents.parse_incasari_xml import parse_incasari_xml
from markus_mcp.tools.saga.documents.validate import validate


FACTURI_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Facturi>
  <Factura>
    <Antet>
      <FacturaNumar>K003</FacturaNumar>
      <FacturaData>15.08.2026</FacturaData>
      <FacturaScadenta>30.08.2026</FacturaScadenta>
      <ClientNume>FAKE NORD LOGISTICS</ClientNume>
      <ClientCod>C001</ClientCod>
      <FacturaMoneda>RON</FacturaMoneda>
    </Antet>
    <Linie>
      <Descriere>Transport</Descriere>
      <Cantitate>1</Cantitate>
      <Pret>100</Pret>
      <Valoare>100</Valoare>
      <TVA>21</TVA>
      <TVAProc>21</TVAProc>
      <Cont>704</Cont>
    </Linie>
  </Factura>
</Facturi>
"""

INCASARI_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Incasari>
  <Linie>
    <Data>15.08.2026</Data>
    <Numar>OP1</Numar>
    <Suma>121.00</Suma>
    <Cont>5121</Cont>
    <Explicatie>Incasare K003</Explicatie>
    <FacturaNumar>K003</FacturaNumar>
    <Moneda>RON</Moneda>
  </Linie>
</Incasari>
"""


class ParseFacturiTests(unittest.TestCase):
    def test_maps_header_and_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "F_test.xml"
            path.write_text(FACTURI_XML, encoding="utf-8")
            parsed = parse_facturi_xml(path)
        self.assertEqual(parsed["kind"], "Facturi")
        self.assertEqual(parsed["invoice_count"] if "invoice_count" in parsed else len(parsed["invoices"]), 1)
        invoice = parsed["invoices"][0]
        self.assertEqual(invoice["number"], "K003")
        self.assertEqual(invoice["client"], "FAKE NORD LOGISTICS")
        document = parsed["documents"][0]
        self.assertEqual(document["kind"], "sales_invoice")
        self.assertEqual(document["header"]["NrDoc"], "K003")
        self.assertEqual(document["header"]["Client"], "FAKE NORD LOGISTICS")
        self.assertEqual(document["header"]["Cod"], "C001")
        self.assertEqual(document["lines"][0]["Cont"], "704")
        self.assertEqual(document["lines"][0]["Denumire"], "Transport")
        self.assertEqual(document["lines"][0]["TVA_ART"], "21")
        errors = validate("iesiri", document)
        self.assertEqual(errors, [])


class ParseIncasariTests(unittest.TestCase):
    def test_maps_bank_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "I_15_08_2026.xml"
            path.write_text(INCASARI_XML, encoding="utf-8")
            parsed = parse_incasari_xml(path)
        self.assertEqual(parsed["kind"], "Incasari")
        self.assertEqual(parsed["line_count"], 1)
        self.assertEqual(parsed["default_account"], "5121")
        entry = parsed["document"]["entries"][0]
        self.assertEqual(entry["NrDoc"], "OP1")
        self.assertEqual(entry["Suma"], "121.0")
        self.assertEqual(entry["FacturaNumar"], "K003")
        self.assertEqual(entry["Cont"], "5121")


if __name__ == "__main__":
    unittest.main()
