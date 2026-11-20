# Models, datasets and evaluation

[README](../README.md) · [Architecture](architecture.md) · [Operations](operations.md)

## Runtime models

### PaddleOCR

`services/models/paddle_model.py` uses PaddleOCR `TextRecognition` with
`model_name="PP-OCRv6_medium_rec"` and `PADDLE_MODEL_DIR`. The default
`medium_digit_rec_v2/inference` export has a digit dictionary, CTC decoding and
a `[3, 64, 320]` padded input shape. It recognizes an isolated display row; it
is not a full-scene text detector.

Training starts from the official
[PP-OCRv6 medium configuration](https://github.com/PaddlePaddle/PaddleOCR/blob/v3.7.0/configs/rec/PP-OCRv6/PP-OCRv6_medium_rec.yml):
SVTR_LCNet, a PPLCNetV4 medium backbone and a multi-head training setup. The
notebook adapts vocabulary, image shape and training data. Compatible pretrained
layers are reused; vocabulary-dependent layers with incompatible shapes are
reinitialized.

The CPU container pins PaddleOCR 3.7.0, PaddlePaddle 3.3.1 and PaddleX 3.7.2.
Colab training has its own pinned GPU environment. Prediction calls are
serialized per lazy-loaded model instance.

### YOLO

`services/models/yolo_model.py` loads the Ultralytics artifact at
`YOLO_MODEL_PATH`, default `services/weights/model1-new.pt`. Prediction uses
confidence 0.5 and IoU 0.4. `YOLO_MODEL_TYPE` selects `D0`–`D9` versus numeric
class mapping; default type 1. Digits are assembled left to right.

Crop one row and mask unrelated digits before inference. A reproducible YOLO
training run, source-data manifest and held-out mAP/sequence accuracy are not
included. PaddleOCR results below must not be reported as YOLO results.

### Numeric scope

The running application extracts unsigned integers. The notebook's default
`digits_only` policy preserves leading zeros for sequence evaluation, removes
decimal separators during label normalization and excludes negative labels.
Signed/decimal support requires coordinated vocabulary, label and extractor
changes. Raw temperature `217` becomes 21.7 °C through the reporting scale;
scale is not inferred from the number of digits.

## Data sources and preparation

There is a private target-domain set plus three external sources. External
images are downloaded during training, not redistributed as a new dataset here.

| Source | Input → accepted in recorded run | Handling |
| --- | --- | --- |
| Private display crops | 2,087 rows → 1,692 unique images | 1,392 train / 148 validation / 152 test. |
| [MiXaiLL76/7SEG_OCR](https://huggingface.co/datasets/MiXaiLL76/7SEG_OCR) | 3,333 → 1,643 | Excludes 1,671 negative-label rows and 19 personal hold-out labels. |
| [chakibmed/bp-monitor-seven-segment](https://huggingface.co/datasets/chakibmed/bp-monitor-seven-segment) | 201 `dev` + 187 `test` digits → 388 | Both source partitions are training data here. |
| [renjithsasidharan/seven-segment-ocr](https://github.com/renjithsasidharan/seven-segment-ocr) | 319 → 319 | Recognition crops using `data/ocr_training_data/gt.txt`. |

7SEG_OCR is pinned to `59873e636d5bd8bd850b3ba5788ee761cef5e895`. The other
sources are not commit-pinned in the notebook; record resolved versions for a
reproduction. Counts describe one run, not future upstream downloads.

The blood-pressure dataset's full screens contain multiple readings. Only its
labelled single-digit crops are used, avoiding a false single-number label for
an entire multi-row image. Its upstream `test` split cannot then serve as an
independent benchmark for this trained model.

With seed 42, personal labels are assigned by stable hash to approximately
80/10/10 train/validation/test buckets. Saved assignments prevent accidental
reshuffling. Public strings matching personal hold-out labels are excluded in
label-split mode. Pixel duplicates and contradictory labels are checked across
sources; corrupt images or conflicting labels stop preparation.

There are 2,350 accepted external images and **3,742 unique training images**.
`TARGET_PERSONAL_FRACTION=0.50` balances mixed sampling contribution, not unique
file counts. Augmentation applies to training; validation/test are unaugmented.
Previews and full-batch preflight checks precede model training.

Distinct video frames can still be correlated. Use `PERSONAL_SPLIT_BY="group"`
and independent camera/session groups for a stronger evaluation. Pixel deduplication
alone cannot prevent session leakage. Results from different split policies are
not directly comparable.

## Recorded evaluation

[evaluation.json](evaluation.json) transcribes saved outputs from the uploaded
notebook before execution outputs were cleared for the repository. It retains
aggregate values only. Private images/prediction rows are not redistributed and
training was not rerun for this documentation update.

| Split | Images | Exact matches | Exact accuracy | CER |
| --- | ---: | ---: | ---: | ---: |
| Personal validation | 148 | 139 | 93.9189% | 2.9046% |
| Personal test | 152 | 129 | 84.8684% | 7.5547% |

Exact accuracy counts fully correct label strings. CER is total Levenshtein
edits divided by total ground-truth characters; lower is better. Neither is
model confidence. Selection used validation accuracy followed by CER; the
selected stage was `mixed`.

Neither hold-out split has a zero-only label. Zero-specific accuracy is `null`,
not 100%. Software tests verify zero handling, not recognition quality.

This is one experiment with a small private hold-out set. It does not establish
cross-facility accuracy, sustained throughput, YOLO performance or end-to-end
record completeness. No published evaluated-checkpoint hash links this run to
every bundled weight file. Evaluate the exact deployed artifact on representative
crops before quoting deployment accuracy, including misreadings in the results.

## Reproduce or extend the experiment

1. Open [the notebook](../notebooks/PP_OCRv6_medium_3datasets.ipynb) with a GPU-enabled
   Colab runtime and install its pinned dependencies.
2. Set private Drive/data paths and supply reviewed labels through `labels.tsv`
   or the configured filename convention.
3. Choose vocabulary, split mode, input shape and external-source flags. Preserve
   split assignments when comparing experiments.
4. Inspect preparation reports/previews and complete the full-batch preflight.
5. Train the mixed stage: configured default 35 epochs, learning rate 0.0002;
   validation selects the best epoch.
6. Review the recovery cell: **cell index 29 forces `PERSONAL_ADAPT_EPOCHS=0`**
   and reconstructs mixed-only candidates, overriding the earlier 15-epoch
   setting. Deliberately revise that path to use optional personal adaptation;
   changing only the initial setting is insufficient.
7. Select candidates on validation, then use test for final reporting rather
   than repeated tuning.
8. Export and validate inference predictions. Retain configuration, split/source
   manifests, metrics, prediction CSVs, attribution and a model hash.

Example manifest, with paths relative to your private image directory:

```tsv
path	label	group
camera_a/frame_001.jpg	0000	camera_a_session_1
camera_b/frame_002.jpg	0145	camera_b_session_2
```

Point `PADDLE_MODEL_DIR` at a complete export with `inference.json`,
`inference.pdiparams` and `inference.yml` plus matching vocabulary. The Dockerfile
copies the default artifact: rebuild the model image after replacement. A new
training checkpoint alone does not update a running service.

## Attribution

Preserve dataset cards, resolved revisions and upstream notices. PaddleOCR,
PaddlePaddle, Ultralytics, external datasets and private imagery have separate
redistribution requirements. The notebook exports `DATA_SOURCES.txt`; it does
not grant rights to source images or publish the private camera collection.
