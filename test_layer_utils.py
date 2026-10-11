
from layer_utils import ocr_results_to_layers, validate_layers

sample_ocr = [
    {
        "text": "SUMMER SALE",
        "bbox": {
            "x": 100,
            "y": 80,
            "width": 300,
            "height": 50
        },
        "confidence": 0.98
    },
    {
        "text": "50% OFF",
        "bbox": {
            "x": 150,
            "y": 180,
            "width": 200,
            "height": 60
        },
        "confidence": 0.95
    }
]

layers = ocr_results_to_layers(sample_ocr, 1536, 1024)

valid, message = validate_layers(layers)

print("Generated layers:", len(layers))
print("Validation:", message)
print("First layer:", layers[0])

assert len(layers) == 2
assert valid

print("All tests passed!")