# Lesson sources for exercising the parse

Real lesson documents, kept here so the content pipeline can be run end to end
against something that actually reaches every part of it.

`simple-interest-jss3.md` is written to force all five modalities out of the
parser. Calculation is the one that matters: it only appears when the source
carries arithmetic the model can decompose into co-construction steps, and no
lesson in the live library has ever produced one. The two worked examples with
their numbered steps are there for that, the rectangle-in-bands passage is
there to earn a diagram, and the practice questions are there for the
interactive variant.

`test_lesson_fixtures.py` holds those properties in place. Edit the document
freely, but if a change strips out what a modality depends on, that test says
so rather than leaving somebody to discover it in a parse run weeks later.

## Running one through

Upload it the way a teacher would, then poll:

    curl -s -X POST https://api.nevolearning.com/api/content/upload \
      -H "Authorization: Bearer $TOKEN" \
      -F "file=@tests/fixtures/lessons/simple-interest-jss3.md"

The 202 carries a `pollUrl`. What to check on the finished lesson:

- `fallbackSegmentCount` is 0, meaning the model wrote it rather than the
  deterministic splitter
- a segment with `contentType: "calculation"` whose `calculationVariant` has a
  populated `answer`
- `visualVariant` present on the diagram segment
- `recap` and `assessment` present on the lesson

Image generation needs credit on the OpenAI account. Without it every picture
fails with a 429 carrying `credit_balance_exhausted`, which the run's review
notes will say in as many words.
