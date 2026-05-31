import random

import pytest
from google.protobuf.json_format import ParseDict

import session_pb2
from news_process import GeneratorConfigError, checkConfig, selectAttr


# ---------- selectAttr ----------

def test_selectAttr_single_certain_key():
    assert selectAttr({'a': 1.0}) == 'a'


def test_selectAttr_empty_dict():
    assert selectAttr({}) is None


def test_selectAttr_underweight_can_return_none():
    # When probabilities sum below 1.0, some random.random() draws fall above
    # the cumulative total and no key is selected. checkConfig() guards against
    # this for the transition matrix; other selectors (channel/campaign/...) do not.
    random.seed(0)
    results = {selectAttr({'a': 0.1}) for _ in range(200)}
    assert None in results


def test_selectAttr_distribution_matches_weights():
    random.seed(42)
    counts = {'a': 0, 'b': 0}
    n = 20000
    for _ in range(n):
        counts[selectAttr({'a': 0.3, 'b': 0.7})] += 1
    assert abs(counts['a'] / n - 0.3) < 0.02


# ---------- checkConfig ----------

def _valid_config():
    return {
        'StateMachine': {
            'States': ['home', 'exitSession'],
            'StateTransitionMatrix': {
                'default': {
                    'home': {'home': 0.5, 'exitSession': 0.5},
                },
            },
        },
    }


def test_checkConfig_accepts_valid():
    checkConfig(_valid_config())  # should not raise


def test_checkConfig_rejects_rows_not_summing_to_one():
    cfg = _valid_config()
    cfg['StateMachine']['StateTransitionMatrix']['default']['home']['exitSession'] = 0.3
    with pytest.raises(GeneratorConfigError):
        checkConfig(cfg)


def test_checkConfig_rejects_unknown_origin_state():
    cfg = _valid_config()
    cfg['StateMachine']['StateTransitionMatrix']['default']['bogus'] = {
        'home': 0.5, 'exitSession': 0.5,
    }
    with pytest.raises(GeneratorConfigError):
        checkConfig(cfg)


def test_checkConfig_rejects_transitions_missing_a_state():
    cfg = _valid_config()
    cfg['StateMachine']['StateTransitionMatrix']['default']['home'] = {'home': 1.0}
    with pytest.raises(GeneratorConfigError):
        checkConfig(cfg)


# ---------- protobuf round-trip ----------

def _session_record():
    """Mirror the dict shape emitSession() builds (news_process.py:emitSession)."""
    return {
        'timestamp': 1700000000,
        'recordType': 'session',
        'useragent': 'pytest-agent',
        'statesVisited': ['home', 'content', 'plusContent'],
        'sid': 42,
        'uid': 'u000042',
        'isSubscriber': 1,
        'campaign': 'fb-1 Be Informed',
        'channel': 'social media',
        'gender': 'm',
        'age': '36-50',
        'latitude': 12.34,
        'longitude': 56.78,
        'place_name': 'Testville',
        'country_code': 'US',
        'timezone': 'America/New_York',
        'home': 1,
        'content': 1,
        'clickbait': 0,
        'subscribe': 0,
        'plusContent': 1,
        'affiliateLink': 0,
        'exitSession': 0,
    }


def test_session_proto_roundtrip_preserves_all_fields():
    msg = session_pb2.Session()
    ParseDict(_session_record(), msg, ignore_unknown_fields=False)

    assert msg.sid == 42
    assert msg.uid == 'u000042'
    assert msg.record_type == 'session'
    assert msg.is_subscriber == 1
    assert list(msg.states_visited) == ['home', 'content', 'plusContent']
    assert msg.place_name == 'Testville'
    assert msg.country_code == 'US'

    # Per-state flags — these are the fields that drift if StateMachine.States
    # ever diverges from session.proto.
    assert msg.home == 1
    assert msg.content == 1
    assert msg.clickbait == 0
    assert msg.plusContent == 1
    assert msg.exitSession == 0


def test_session_proto_rejects_unknown_field_when_strict():
    record = _session_record()
    record['noSuchField'] = 'oops'
    msg = session_pb2.Session()
    with pytest.raises(Exception):  # ParseError is a subclass of Exception
        ParseDict(record, msg, ignore_unknown_fields=False)
