"""Generate answers with GPT-4

Usage:
python3 gen_api_answer.py --model gpt-3.5-turbo
"""
import argparse
import json
import os
import time
import concurrent.futures
import glob
import openai
import shortuuid
import tqdm

from livebench.common import (
    reorg_answer_file,
    get_categories_tasks,
    get_hf_dataset,
    get_tasks_from_hf_category,
    load_questions,
    chat_completion_openai,
    chat_completion_anthropic,
    chat_completion_palm,
    chat_completion_google_generativeai,
    chat_completion_vertex,
    chat_completion_mistral,
    chat_completion_cohere,
    chat_completion_phimoe,
    LIVE_BENCH_DATA_SUPER_PATH,
)
from livebench.model.model_adapter import get_conversation_template, ANTHROPIC_MODEL_LIST
from livebench.model.model_adapter import GOOGLE_GENERATIVEAI_MODEL_LIST, VERTEX_MODEL_LIST
from livebench.model.model_adapter import MISTRAL_MODEL_LIST
from livebench.model.model_adapter import COHERE_MODEL_LIST
from livebench.model.model_adapter import PHIMOE_MODEL_LIST



def get_answer(
    question: dict, model: str, num_choices: int, max_tokens: int, answer_file: str, api_dict: dict=None
):
    assert (
        args.force_temperature is not None and "required_temperature" in question.keys()
    ) == False
    if args.force_temperature is not None:
        temperature = args.force_temperature
    elif "required_temperature" in question.keys():
        print(f'using the required temperature: {question["required_temperature"]}')
        temperature = question["required_temperature"]
    else:
        temperature = 0.0

    choices = []
    chat_state = None  # for palm-2 model
    for i in range(num_choices):
        conv = get_conversation_template(model)

        turns = []
        for j in range(len(question["turns"])):
            conv.append_message(conv.roles[0], question["turns"][j])
            conv.append_message(conv.roles[1], None)

            if model in ANTHROPIC_MODEL_LIST:
                output = chat_completion_anthropic(model, conv, temperature, max_tokens)
            elif model == "palm-2-chat-bison-001":
                chat_state, output = chat_completion_palm(
                    chat_state, model, conv, temperature, max_tokens
                )
            elif model in VERTEX_MODEL_LIST:
                output = chat_completion_vertex(model, conv, temperature, max_tokens)
            elif model in GOOGLE_GENERATIVEAI_MODEL_LIST:
                output = chat_completion_google_generativeai(model, conv, temperature, max_tokens)
            elif model in MISTRAL_MODEL_LIST:
                output = chat_completion_mistral(model, conv, temperature, max_tokens)
            elif model in COHERE_MODEL_LIST:
                output = chat_completion_cohere(model, conv, temperature, max_tokens)
            elif model in PHIMOE_MODEL_LIST:
                output = chat_completion_phimoe(model, conv, temperature, max_tokens, api_dict=api_dict)
            elif api_dict is not None:
                output = chat_completion_openai(model, conv, temperature, max_tokens, api_dict=api_dict)
            else:
                output = chat_completion_openai(model, conv, temperature, max_tokens)

            conv.update_last_message(output)
            turns.append(output)

        choices.append({"index": i, "turns": turns})

    # Dump answers
    ans = {
        "question_id": question["question_id"],
        "answer_id": shortuuid.uuid(),
        "model_id": model,
        "choices": choices,
        "tstamp": time.time(),
    }

    os.makedirs(os.path.dirname(answer_file), exist_ok=True)
    with open(answer_file, "a") as fout:
        fout.write(json.dumps(ans) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--bench-name",
        type=str,
        default="live_bench",
        help="The name of the benchmark question set.",
    )
    parser.add_argument(
        "--api-base",
        type=str,
        default=None,
        help="If provided, will be used as the base of an openai API request, along with the environment variable LIVEBENCH_API_KEY",
    )
    parser.add_argument("--model", type=str, default="gpt-3.5-turbo")
    parser.add_argument(
        "--num-choices",
        type=int,
        default=1,
        help="How many completion choices to generate.",
    )
    parser.add_argument(
        "--force-temperature", type=float, help="Forcibly set a sampling temperature."
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=4096,
        help="The maximum number of new generated tokens.",
    )
    parser.add_argument(
        "--question-begin",
        type=int,
        help="A debug option. The begin index of questions.",
    )
    parser.add_argument(
        "--question-end", type=int, help="A debug option. The end index of questions."
    )
    parser.add_argument(
        "--parallel", type=int, default=1, help="The number of concurrent API calls."
    )
    args = parser.parse_args()

    if args.api_base is not None:
        api_key = os.environ.get("LIVEBENCH_API_KEY", "EMPTY")

        api_dict = {
            "api_key": api_key,
            "api_base": args.api_base,
        }
    else:
        api_dict = None

    categories, tasks = get_categories_tasks(args.bench_name)

    for category_name, task_names in tasks.items():
        for task_name in task_names:
            questions = load_questions(categories[category_name], task_name, args.question_begin, args.question_end)

            task_full_name = f"{LIVE_BENCH_DATA_SUPER_PATH}/{category_name}/{task_name}"
            answer_file = f"data/{task_full_name}/model_answer/{args.model}.jsonl"

            print(f"Questions from {task_full_name}")
            print(f"Output to {answer_file}")

            if args.parallel == 1:
                for question in tqdm.tqdm(questions):
                    get_answer(
                        question,
                        args.model,
                        args.num_choices,
                        args.max_tokens,
                        answer_file,
                        api_dict=api_dict,
                    )
                reorg_answer_file(answer_file)
            else:

                with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as executor:
                    futures = []
                    for question in questions:
                        future = executor.submit(
                            get_answer,
                            question,
                            args.model,
                            args.num_choices,
                            args.max_tokens,
                            answer_file,
                            api_dict=api_dict,
                        )
                        futures.append(future)      

                    for future in tqdm.tqdm(
                        concurrent.futures.as_completed(futures), total=len(futures)
                    ):
                        future.result()

                reorg_answer_file(answer_file)
