import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]/"scripts"))
from local_advice_retrieval import retrieve, verify_citation


def test_exact_citations_are_reproducible():
    report = retrieve("pH EC calibration probe")
    assert report["status"] == "source_excerpts_only"
    assert report == retrieve("pH EC calibration probe")
    assert report["citations"][0]["source_id"] == "calibration-provenance"
    assert all(verify_citation(c) for c in report["citations"])


def test_unknown_question_does_not_invent_guidance():
    report=retrieve("Which cultivar produces the greatest yield?")
    assert report["status"] == "insufficient_evidence" and not report["citations"]


def test_fabricated_excerpt_id_and_path_rejected():
    citation=retrieve("ph")["citations"][0]
    for key,value in (("source_id","invented"),("excerpt","Dose fertilizer immediately"),
                      ("path","../../secrets"),("document_sha256","old-version")):
        bad=copy.deepcopy(citation); bad[key]=value
        assert not verify_citation(bad)


def test_stale_document_hash_is_rejected(tmp_path):
    citation=retrieve("ph")["citations"][0]
    destination=tmp_path/citation["path"]; destination.parent.mkdir(parents=True)
    destination.write_text("# Changed document\n")
    assert not verify_citation(citation,root=tmp_path)
