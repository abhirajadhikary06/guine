#!/usr/bin/env python3
"""Simple STT script using SpeechRecognition + Google Web Speech only."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import speech_recognition as sr


def transcribe_with_google(audio_path: Path, language: str) -> str:
	recognizer = sr.Recognizer()

	# SpeechRecognition's AudioFile supports WAV, AIFF/AIFC, and FLAC.
	with sr.AudioFile(str(audio_path)) as source:
		audio_data = recognizer.record(source)

	return recognizer.recognize_google(audio_data, language=language)


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Transcribe audio with Google Web Speech via SpeechRecognition.",
	)
	default_audio = Path(__file__).resolve().parent / "test.wav"
	parser.add_argument(
		"audio_file",
		nargs="?",
		default=str(default_audio),
		help=f"Path to input audio file (wav/aiff/flac). Default: {default_audio.name}",
	)
	parser.add_argument(
		"--language",
		default="en-US",
		help="Language code for recognition (default: en-US)",
	)
	return parser.parse_args()


def main() -> int:
	args = parse_args()
	audio_path = Path(args.audio_file)

	if not audio_path.exists() or not audio_path.is_file():
		print(f"File not found: {audio_path}")
		return 1

	print("--- SpeechRecognition (Google Web Speech) ---")
	print(f"Input: {audio_path}")
	print(f"Language: {args.language}")

	start_time = time.time()
	try:
		text = transcribe_with_google(audio_path, args.language)
		elapsed = time.time() - start_time
		print(f"Transcript: {text}")
		print(f"Time Taken: {elapsed:.2f} seconds")
		return 0
	except sr.UnknownValueError:
		print("SpeechRecognition could not understand audio")
		return 2
	except sr.RequestError as exc:
		print(f"Could not request results from Google Web Speech service; {exc}")
		return 3
	except ValueError as exc:
		print(f"Invalid audio input: {exc}")
		print("Use WAV, AIFF/AIFC, or FLAC.")
		return 4


if __name__ == "__main__":
	raise SystemExit(main())
