def test_model_metadata_is_explicit():
    import backend.detector as detector
    meta=detector.model_metadata()
    assert meta.get('model') == detector.MODEL_NAME
    assert meta.get('status') == 'prototype'

def test_probability_output_is_bounded():
    import numpy as np
    from backend.detector import detect_candidate_from_array
    p=detect_candidate_from_array(np.zeros((8,8)),np.zeros((8,8)))
    assert p.min() >= 0 and p.max() <= 1
