# Deck tooling

The idea presentation is generated, not hand-edited, so its numbers can never
drift from what the database actually holds.

```bash
python3 tools/make_deck_charts.py     # booking curve + late-booking premium
python3 tools/make_carrier_chart.py   # carrier coverage
python3 tools/build_deck.py           # fills the SIH template -> SIH26056-Idea-Presentation.pptx
```

Every chart is drawn from live Supabase rows. Re-run all three after a scrape
and the deck reflects the current data.

`build_deck.py` asserts its own layout: it fails loudly if a section would
overflow a slide or collide with the template's footer, rather than producing
a deck that only looks wrong once opened.
