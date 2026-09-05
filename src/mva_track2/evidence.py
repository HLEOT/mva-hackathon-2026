"""Collect public MVA knowledge before joining any patient-derived result.

Search coverage and missing sources are recorded explicitly. Drug approval in
another indication is not evidence of efficacy or safety for MVA or children.
"""
from __future__ import annotations

import json
import re
from xml.etree import ElementTree

from mva_track1.common import PROJECT_ROOT, Track1Error, atomic_write_json, load_jsonish, sha256_file, utc_now
from .sources import ROOT, fetch, payload


# Explicit identities documented in the FDA originator application records.
# Never strip arbitrary salt suffixes or use substring matches: that could
# merge different active substances or approve a fixed-dose combination as a
# single-agent intervention. Approval history is not current availability.
FDA_SALT_IDENTITIES = {
    "metformin": {"ingredient": "metformin hydrochloride",
        "source_url": "https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=overview.process&ApplNo=020357"},
    "pravastatin": {"ingredient": "pravastatin sodium",
        "source_url": "https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=overview.process&ApplNo=019898"},
}


def abstracts(xml: str) -> list[dict]:
    if not xml:
        return []
    result = []
    for article in ElementTree.fromstring(xml).findall(".//PubmedArticle"):
        pmid = article.findtext(".//MedlineCitation/PMID", "")
        if not re.fullmatch(r"\d+", pmid):
            continue
        title = "".join(article.find(".//ArticleTitle").itertext())
        abstract = "\n".join("".join(node.itertext()) for node in article.findall(".//AbstractText"))
        result.append({"id": f"PMID:{pmid}", "pmid": pmid, "title": title, "abstract": abstract,
                       "publication_types": [node.text for node in article.findall(".//PublicationType")],
                       "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"})
    return result


def approved_applications(records: list, drug: str) -> list[dict]:
    """Require a traceable single-ingredient product and original approval."""
    approvals = []
    name = drug.strip().casefold()
    salt = FDA_SALT_IDENTITIES.get(name)
    accepted = {name} | ({salt["ingredient"]} if salt else set())
    for record in records:
        products = []
        for product in record.get("products", []):
            ingredients = product.get("active_ingredients", [])
            if len(ingredients) != 1:
                continue
            ingredient = ingredients[0].get("name", "").strip().casefold()
            if ingredient not in accepted:
                continue
            products.append({key: product.get(key) for key in ["product_number", "brand_name",
                "active_ingredients", "dosage_form", "route", "marketing_status"]} | {
                "identity_match": "exact_name" if ingredient == name else "explicit_salt_identity",
                "identity_source_url": salt["source_url"] if ingredient != name else None})
        if not products:
            continue
        events = [s for s in record.get("submissions", [])
                  if s.get("submission_status") == "AP" and s.get("submission_type") == "ORIG"]
        number = record.get("application_number", "")
        if events and re.fullmatch(r"(?:NDA|ANDA|BLA)\d+", number):
            approvals.append({"application_number": number, "jurisdiction": "United States FDA",
                "events": events, "matched_single_ingredient_products": products,
                "approval_scope": "historical original approval; not MVA approval or current market availability",
                "url": "https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=overview.process&ApplNo=" + re.sub(r"\D", "", number)})
    return approvals


def prepare() -> None:
    cfg = load_jsonish(PROJECT_ROOT / "config/track2.yaml")
    requests, literature, genes, drugs = [], {}, {}, {}

    def get(source, path, params=None, xml=False):
        receipt = fetch(source, path, params, xml=xml)
        requests.append(receipt)
        return payload(receipt)

    metadata = {"chembl": get("chembl", "status.json"), "reactome": get("reactome", "data/database/version")}
    queries = dict(cfg["literature_queries"])
    # Every gene/compound query is public and fixed by config, not derived from
    # the patient's highest ranked gene or phenotype.
    queries.update({f"gene_{gene}": f'{gene} AND ("mosaic variegated aneuploidy" OR aneuploidy)' for gene in cfg["public_genes"]})
    queries.update({f"drug_{drug}": f'{drug} AND (aneuploidy OR "chromosomal instability" OR BUBR1)' for drug in cfg["drug_search_space"]})
    search_coverage = {}
    for name, query in queries.items():
        found = get("entrez", "esearch", {"db": "pubmed", "term": query, "retmode": "json", "retmax": 10, "sort": "relevance"})
        result = found.get("esearchresult", {})
        ids = result.get("idlist", [])
        search_coverage[name] = {"query": query, "total_hits": result.get("count"), "retrieved_ids": ids,
                                 "bounded_search": True, "ok": bool(result)}
        if ids:
            for article in abstracts(get("entrez", "efetch", {"db": "pubmed", "id": ",".join(ids), "retmode": "xml"}, xml=True)):
                literature[article["id"]] = article
    pathways = []
    for identifier in cfg["reactome_seeds"]:
        record = get("reactome", "data/query/" + identifier)
        if record.get("stId") != identifier:
            continue
        participants = get("reactome", "data/participants/" + identifier)
        pathways.append({"id": identifier, "name": record.get("displayName", ""),
            "version": record.get("stIdVersion"), "summation": record.get("summation", []),
            "literature": record.get("literatureReference", []), "participants": participants,
            "url": "https://reactome.org/content/detail/" + identifier})
    for gene in cfg["public_genes"]:
        # A text mention is recorded honestly; it is not automatically promoted
        # to curated membership or a directed mechanism of intervention.
        mentions = [p["id"] for p in pathways if re.search(r"\b" + re.escape(gene) + r"\b", json.dumps(p))]
        genes[gene] = {"pathway_text_mentions": mentions, "curated_membership": "not_independently_verified"}
    for drug in cfg["drug_search_space"]:
        matches = get("chembl", "molecule.json", {"pref_name__iexact": drug, "limit": 10}).get("molecules", [])
        compounds = [m for m in matches if str(m.get("pref_name", "")).lower() == drug.lower()]
        record = {"name": drug, "compounds": [], "approval": [], "labels": []}
        for molecule in compounds:
            identifier = molecule["molecule_chembl_id"]
            mechanisms = get("chembl", "mechanism.json", {"molecule_chembl_id": identifier, "limit": 10}).get("mechanisms", [])
            warnings = get("chembl", "drug_warning.json", {"molecule_chembl_id": identifier, "limit": 10}).get("drug_warnings", [])
            record["compounds"].append({"id": identifier, "name": molecule.get("pref_name"), "max_phase": molecule.get("max_phase"),
                "mechanisms": mechanisms, "warnings": warnings, "url": "https://www.ebi.ac.uk/chembl/explore/compound/" + identifier})
        fda = get("fda", "drug/drugsfda.json", {"search": f'products.active_ingredients.name:"{drug.upper()}"', "limit": 10})
        record["approval"] = approved_applications(fda.get("results", []), drug)
        labels = get("fda", "drug/label.json", {"search": f'openfda.generic_name:"{drug}"', "limit": 3}).get("results", [])
        for label in labels:
            identifier = label.get("set_id", "")
            if not re.fullmatch(r"[0-9a-fA-F-]{36}", identifier):
                continue
            record["labels"].append({"id": identifier, "effective_time": label.get("effective_time"),
                "url": "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=" + identifier,
                **{field: label.get(field, []) for field in ["boxed_warning", "warnings", "warnings_and_cautions", "contraindications",
                    "adverse_reactions", "pediatric_use", "indications_and_usage", "mechanism_of_action"]}})
        drugs[drug] = record
    corpus = {"created_at": utc_now(), "metadata": metadata, "literature": list(literature.values()),
              "genes": genes, "pathways": pathways, "drugs": drugs, "search_coverage": search_coverage,
              "limitations": ["Bounded literature searches are not a systematic review.",
                  "Pathway membership is not therapeutic evidence.", "Regulatory approval is for an existing indication, not MVA.",
                  "Labels may differ by formulation and are not paediatric dosing guidance."]}
    ROOT.mkdir(parents=True, exist_ok=True)
    corpus_path = ROOT / "corpus.json"
    atomic_write_json(corpus_path, corpus, mode=0o644)
    coverage = {source: {"attempted": sum(r["source"] == source for r in requests),
                         "successful": sum(r["source"] == source and r["ok"] for r in requests)}
                for source in ["entrez", "reactome", "chembl", "fda"]}
    manifest = {"schema_version": 1, "created_at": utc_now(), "configuration_sha256": sha256_file(PROJECT_ROOT / "config/track2.yaml"),
                "corpus_sha256": sha256_file(corpus_path), "coverage": coverage, "requests": requests,
                "literature_records": len(literature), "patient_data_used_in_external_queries": False}
    atomic_write_json(ROOT / "manifest.json", manifest, mode=0o644)
    if not literature or not pathways or any(value["successful"] == 0 for value in coverage.values()):
        raise Track1Error("A required public evidence source is unavailable; partial results retained")
