# APIx Statistical Portal

The institutional view. No consumer features — this is an instrument for
tracking airfare inflation to augment CPI, not a price-comparison site.

| Section | Purpose |
|---|---|
| Headline APIx | The index, with a **provisional** badge and the reason whenever coverage is below the publication threshold |
| Index movement | The series over time |
| Sub-indices by lead time | The same Jevons calculation per booking bucket — divergence between them is what a single average hides |
| Fare movement alerts | Routes past ±15% from base, flagged for review |
| Carrier comparison | Airline mix is *not* controlled for in the index; this is the diagnostic that shows why |
| Methodology & provenance | Method, weights, base period, cell rule, outlier rule, publication rule, collection cadence, export endpoint |

The browser mirrors `engine/engine.py` rather than inventing a second method,
and the two agree: both report **APIx 82.00** at 46% basket weight on the same
data. If they ever diverge, that is a bug worth finding.
