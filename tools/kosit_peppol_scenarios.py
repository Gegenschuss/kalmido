#!/usr/bin/env python3
"""2.154.0 B (#1960): writes scenarios-peppol.xml next to the scenarios.xml of the KoSIT XRechnung configuration: the
same scenarios plus two for Peppol BIS Billing 3.0 (UBL Invoice / CreditNote with the Peppol CustomizationID): the UBL
2.1 XML Schema, the EN 16931 Schematron of the configuration and the OpenPeppol rules (PEPPOL-EN16931-UBL.xslt, compiled
Schematron, placed in resources/peppol/ by tools/einvoice_validate.sh). The original file stays as it is.
usage: kosit_peppol_scenarios.py <configuration folder>"""
import os
import sys

CUSTOMIZATION = "urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0"
SCENARIO = """
  <!-- Kalmido (tools/kosit_peppol_scenarios.py): Peppol BIS Billing 3.0, {kind} -->
  <scenario>
    <name>Peppol BIS Billing 3.0 (UBL {kind})</name>
    <description><p>UBL {kind} 2.1 XML Schema, Schematron rules of EN 16931 and the OpenPeppol rules PEPPOL-EN16931-UBL</p></description>
    <namespace prefix="cbc">urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2</namespace>
    <namespace prefix="doc">urn:oasis:names:specification:ubl:schema:xsd:{kind}-2</namespace>
    <namespace prefix="rep">http://www.xoev.de/de/validator/varl/1</namespace>
    <match>exists(/doc:{kind}[cbc:CustomizationID/text() = '{cust}'])</match>
    <validateWithXmlSchema>
      <resource><name>XML Schema for UBL 2.1 {kind}</name><location>resources/ubl/2.1/xsd/maindoc/UBL-{kind}-2.1.xsd</location></resource>
    </validateWithXmlSchema>
    <validateWithSchematron>
      <resource><name>Schematron rules for EN16931 (UBL)</name><location>resources/ubl/2.1/xsl/EN16931-UBL-validation.xsl</location></resource>
    </validateWithSchematron>
    <validateWithSchematron>
      <resource><name>OpenPeppol rules (PEPPOL-EN16931-UBL)</name><location>resources/peppol/PEPPOL-EN16931-UBL.xslt</location></resource>
    </validateWithSchematron>
    <createReport>
      <resource><name>Validation report for Peppol BIS Billing 3.0</name><location>resources/xrechnung-report.xsl</location></resource>
    </createReport>
    <acceptMatch>/rep:report/rep:assessment[1]/rep:accept[1]</acceptMatch>
  </scenario>
"""


def main(conf):
    with open(os.path.join(conf, "scenarios.xml"), encoding="utf-8") as fh:
        text = fh.read()
    if "<noScenarioReport>" not in text:
        print("scenarios.xml without <noScenarioReport>", file=sys.stderr)
        return 2
    extra = "".join(SCENARIO.format(kind=k, cust=CUSTOMIZATION) for k in ("Invoice", "CreditNote"))
    i = text.rindex("  <noScenarioReport>") if "  <noScenarioReport>" in text else text.rindex("<noScenarioReport>")
    with open(os.path.join(conf, "scenarios-peppol.xml"), "w", encoding="utf-8") as fh:
        fh.write(text[:i] + extra.lstrip("\n") + "\n" + text[i:])
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
