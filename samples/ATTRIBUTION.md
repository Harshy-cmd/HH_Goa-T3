# Sample Images

Sample face images are **not committed** to this repository because they are
biometric data. Place your own test image in this directory:

```bash
cp /path/to/your/photo.jpg samples/input.jpg
```

## Requirements for a good test image

- A **clear, front-facing** portrait where the face is reasonably large
- An image of someone whose face **actually appears publicly** on the web
  (otherwise reverse-image search will correctly return no results)
- JPEG, PNG, or WebP format

## What NOT to use

- Do not use a private photo that has never been posted online
- Do not use a photo behind a paywall or login
- Do not use a copyrighted press photo without understanding fair use

## During the demo

The pipeline will:
1. Detect the face in your image
2. Search the web for visual matches
3. Download and face-verify candidates
4. Register a fingerprint on the blockchain

The input image itself is never uploaded to the blockchain and is gitignored.
