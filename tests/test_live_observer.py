from datetime import datetime, timedelta, timezone
from atlas.models.live_observer import observe_public_bars


def bars(now, count=8):
    return [{'timestamp': (now - timedelta(seconds=count-i)).isoformat(),
             'open': 100+i, 'high': 102+i, 'low': 99+i, 'close': 101+i, 'volume': 1+i}
            for i in range(count)]


def test_observer_waits_for_later_real_outcome_and_never_relearns_a_bar():
    now = datetime.now(timezone.utc)
    rows = bars(now)
    first = observe_public_bars('TEST-OBS-A', rows, now=now)
    assert first['samples_learned'] == 0
    assert first['probability_up'] == 0.5
    same = observe_public_bars('TEST-OBS-A', rows, now=now)
    assert same['samples_learned'] == 0
    later = {**rows[-1], 'timestamp': now.isoformat(), 'close': 120, 'high': 121}
    # The new bar has not closed yet and cannot label the pending prediction.
    forming = observe_public_bars('TEST-OBS-A', rows + [later], now=now)
    assert forming['samples_learned'] == 0
    next_read = observe_public_bars('TEST-OBS-A', rows + [later], now=now+timedelta(seconds=2))
    assert next_read['samples_learned'] == 1
    assert next_read['recent_outcomes'][-1]['outcome'] == 'UP'
    assert next_read['weights'] != [0, 0, 0]
    repeated = observe_public_bars('TEST-OBS-A', rows + [later], now=now+timedelta(seconds=3))
    assert repeated['samples_learned'] == 1
    assert repeated['weights'] == next_read['weights']
    assert repeated['orders_submitted'] == 0


def test_observer_withholds_missing_and_stale_inputs():
    now = datetime.now(timezone.utc)
    assert observe_public_bars('TEST-OBS-B', [], now=now)['status'] == 'waiting'
    assert observe_public_bars('TEST-OBS-B', bars(now-timedelta(seconds=30)), now=now)['status'] == 'stale'


def test_realtime_reader_never_falls_back_to_fixture_or_demo(monkeypatch):
    from atlas.marketdata import second_tape
    from atlas.marketdata.live_stream import LiveMarketDataGateway
    from atlas.models.chart_reader import read_symbol_chart
    from atlas.models.whale_policy import WhalePolicyModel
    gateway = LiveMarketDataGateway(demo_mode=True)
    gateway.public_fetch_enabled = True
    now = datetime.now(timezone.utc)
    rows = bars(now)
    monkeypatch.setattr(second_tape, 'snapshot', lambda *a, **k: {'candles': rows, 'feed_health': {'connection': 'connected'}})
    read = read_symbol_chart(gateway, WhalePolicyModel(), 'TEST-OBS-C', bucket_seconds=1)
    assert read['chart_source'] == 'public_last_trade'
    assert read['candles'] == rows
    assert read['model_id'] == 'online_logistic_observer:experimental'
    assert read['stream_inputs_observed'] == []
    monkeypatch.setattr(second_tape, 'snapshot', lambda *a, **k: {'candles': []})
    empty = read_symbol_chart(gateway, WhalePolicyModel(), 'NVDA', bucket_seconds=1)
    assert empty['chart_source'] == 'withheld'
    assert empty['candles'] == []
    assert empty['direction'] == 'WITHHELD'


def test_realtime_chart_read_only_watches_selected_listing(monkeypatch):
    from atlas.models import chart_reader
    from atlas.models.whale_policy import WhalePolicyModel
    watched = []
    def read(gateway, model, symbol, **kwargs):
        watched.append(symbol)
        return {"symbol": symbol, "chart_source": "withheld", "bucket_seconds": 1}
    monkeypatch.setattr(chart_reader, "read_symbol_chart", read)
    report = chart_reader.read_market_charts(None, WhalePolicyModel(), symbol="ETH-USD", bucket_seconds=1)
    assert watched == ["ETH-USD"]
    assert report["chart_track"]["follows"] == "same_public_trade_feed"
