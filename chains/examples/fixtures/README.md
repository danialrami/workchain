# Fixtures for the two-input sample chain

`in_b.wav` is the second input consumed by `chains/examples/two-input.yaml`. It is
committed so the sample runs out of the box, and it is fully regenerable — never hand-
edit it.

```bash
ffmpeg -f lavfi -i sine=frequency=880:duration=2 -ac 1 -c:a pcm_s16le in_b.wav
```

(2-second, 880 Hz mono sine, 16-bit PCM — a plain tone whose sha256 the run JSON
records as the `in2` provenance.)