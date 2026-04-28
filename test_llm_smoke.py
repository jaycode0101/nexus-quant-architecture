from dotenv import load_dotenv

from trading_model.llm.provider import get_llm_response


def main() -> None:
    load_dotenv()
    print("Testing configured LLM provider...")
    response = get_llm_response("Reply with exactly one word: SUCCESS")
    print(f"LLM TEST RESULT: {response.strip()}")


if __name__ == "__main__":
    main()
