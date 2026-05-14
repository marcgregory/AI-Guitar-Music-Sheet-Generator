import argparse

from app.tasks import process_audio_transcription


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one transcription task locally.")
    parser.add_argument("transcription_id", type=int)
    args = parser.parse_args()

    result = process_audio_transcription.apply(args=[args.transcription_id], throw=False)
    print(result.state)
    print(repr(result.result))


if __name__ == "__main__":
    main()
