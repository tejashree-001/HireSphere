from app.services.matching import score_resume


def test_skill_score_and_missing_skills():
    result = score_resume("I have Python, SQL, and Flask experience.", "Python, SQL, Java")
    assert result["score"] == 67
    assert result["matched"] == ["python", "sql"]
    assert result["missing"] == ["java"]


def test_empty_skills_return_zero():
    assert score_resume("Python developer", "") == {"score": 0, "matched": [], "missing": []}


def test_tfidf_similarity_is_bounded_and_identical_text_matches():
    from app.services.matching import tfidf_similarity

    assert tfidf_similarity("Python Flask developer", "Python Flask developer") == 100.0
    assert 0 <= tfidf_similarity("Python Flask developer", "accounting finance") <= 100
    assert tfidf_similarity("", "Python") == 0.0
