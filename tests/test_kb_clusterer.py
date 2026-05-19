import kb_clusterer


def test_topic_hash_stable():
    assert kb_clusterer._topic_hash("abc") == kb_clusterer._topic_hash("abc")
    assert kb_clusterer._topic_hash("abc") != kb_clusterer._topic_hash("abd")


def test_cluster_gaps_groups_close_embeddings():
    open_gaps = [
        {"id": 1, "topic": "a", "frequency": 5},
        {"id": 2, "topic": "b", "frequency": 3},
        {"id": 3, "topic": "c", "frequency": 8},
        {"id": 4, "topic": "d", "frequency": 10},
    ]
    embeddings = {
        1: [0.9, 0.1] + [0.0] * 766,
        2: [0.85, 0.15] + [0.0] * 766,
        3: [0.88, 0.12] + [0.0] * 766,
        4: [-0.5, -0.5] + [0.0] * 766,
    }
    clusters = kb_clusterer._cluster_gaps(open_gaps, embeddings)
    assert len(clusters) == 2
    assert sorted(len(c) for c in clusters) == [1, 3]


def test_build_cluster_rows_picks_highest_frequency_rep():
    open_gaps = [
        {"id": 10, "topic": "a", "frequency": 5},
        {"id": 11, "topic": "b", "frequency": 12},
        {"id": 12, "topic": "c", "frequency": 3},
    ]
    rows = kb_clusterer._build_cluster_rows(open_gaps, [[10, 11, 12]])
    assert len(rows) == 1
    assert rows[0]["representative_gap_id"] == 11
    assert rows[0]["label"] == "b"
    assert rows[0]["total_frequency"] == 20


def test_parse_pgvector_handles_str_and_list():
    assert kb_clusterer._parse_pgvector([0.1, 0.2]) == [0.1, 0.2]
    assert kb_clusterer._parse_pgvector("[0.1, 0.2]") == [0.1, 0.2]
    assert kb_clusterer._parse_pgvector(None) is None
