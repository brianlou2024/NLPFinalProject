"""
Generate samples with GPT-2 and filter out those that are likely to be
memorized samples from the training set.
"""

import logging
logging.basicConfig(level='ERROR')

import argparse
import numpy as np
from pprint import pprint
import sys
import torch
import zlib
from transformers import LlamaForCausalLM, LlamaTokenizer
from tqdm import tqdm
import os
import utils
os.environ['TRANSFORMERS_CACHE'] = '/scratch/gpfs/blou/.cache/'

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

def calculatePerplexity(sentence, model, tokenizer):
    """
    exp(loss)
    """
    # print(f"Sentence: {sentence}")
    tmp = tokenizer.encode(sentence)
    # print(f"Tokens: {tmp}")
    input_ids = torch.tensor(tmp).unsqueeze(0)
    # print(input_ids)
    input_ids = input_ids.to(device)
    # print(input_ids)
    with torch.no_grad():
        outputs = model(input_ids, labels=input_ids)
    loss, logits = outputs[:2]
    return torch.exp(loss)

def print_best(metric, samples, name1, scores1, name2=None, scores2=None, n=10):
    """
    print the `n` best samples according to the given `metric`
    """
    idxs = np.argsort(metric)[::-1][:n]

    for i, idx in enumerate(idxs):
        if scores2 is not None:
            print(f"{i+1}: {name1}={scores1[idx]:.3f}, {name2}={scores2[idx]:.3f}, score={metric[idx]:.3f}")
        else:
            print(f"{i+1}: {name1}={scores1[idx]:.3f}, , score={metric[idx]:.3f}")

        print()
        #for line in samples[idx].split("\n"):
        #    print(f"\t {line.rstrip()}")
        pprint(samples[idx])
        print()
        print()

        

def parse_commoncrawl(wet_file):
    """
    Quick and ugly parsing of a WET file.
    Tested for the May 2021 crawl.
    """
    with open(wet_file) as f:
        lines = f.readlines() 
    
    start_idxs = [i for i in range(len(lines)) if "WARC/1.0" in lines[i]]
    
    all_eng = ""

    count_eng = 0
    for i in range(len(start_idxs)-1):
        start = start_idxs[i]
        end = start_idxs[i+1]
        if "WARC-Identified-Content-Language: eng" in lines[start+7]:
            count_eng += 1
            for j in range(start+10, end):
                all_eng += lines[j]

    return all_eng


def main():
    print(f"using device: {device}")

    if args.internet_sampling:
        print("Loading common crawl...")
        cc = parse_commoncrawl(args.wet_file)

    # number of tokens to generate
    seq_len = 256

    # sample from the top_k tokens output by the model
    top_k = 40

    print("Loading LlaMa...")
    
    tokenizer = LlamaTokenizer.from_pretrained("/scratch/gpfs/blou/.llamahugging")
    model1 = LlamaForCausalLM.from_pretrained("/scratch/gpfs/blou/.llamahugging").cuda()
    # tokenizer = GPT2Tokenizer.from_pretrained('gpt2', cache_dir="/scratch/gpfs/blou/.cache/")
    # tokenizer = AutoTokenizer.from_pretrained("lvwerra/LlaMa", cache_dir="/scratch/gpfs/blou/.cache/", padding_side = "left" )
    tokenizer.padding_side = "left" 
    tokenizer.pad_token = tokenizer.eos_token

    # model1 = GPT2LMHeadModel.from_pretrained('gpt2-LlaMa', return_dict=True, cache_dir="/scratch/gpfs/blou/.cache/").to(device)
    # model1 = AutoModelForCausalLM.from_pretrained("lvwerra/LlaMa", return_dict=True, cache_dir="/scratch/gpfs/blou/.cache/").to(device)
    

    model1.config.pad_token_id = model1.config.eos_token_id
    # model2 = GPT2LMHeadModel.from_pretrained('gpt2', return_dict=True, cache_dir="/scratch/gpfs/blou/.cache/").to(device)
    model1.eval()
    # model2.eval()
    
    samples = []
    scores = {"LlaMa": [], "zlib": []}

    num_batches = int(np.ceil(args.N / args.batch_size))
    with tqdm(total=args.N) as pbar:
        for i in range(num_batches):
            # encode the prompts
            if args.internet_sampling:
                # pick a random 10-token prompt in common crawl 

                input_len = 10
                input_ids = []
                attention_mask = []

                while len(input_ids) < args.batch_size:
                    # take some random words in common crawl
                    r = np.random.randint(0, len(cc))
                    prompt = " ".join(cc[r:r+100].split(" ")[1:-1])

                    # make sure we get the same number of tokens for each prompt to enable batching
                    inputs = tokenizer(prompt, return_tensors="pt", max_length=input_len, truncation=True)
                    if len(inputs['input_ids'][0]) == input_len:
                        input_ids.append(inputs['input_ids'][0])
                        attention_mask.append(inputs['attention_mask'][0])

                inputs = {'input_ids': torch.stack(input_ids), 
                          'attention_mask': torch.stack(attention_mask)}

                # the actual truncated prompts
                prompts = tokenizer.batch_decode(inputs['input_ids'], skip_special_tokens=True)
            else:
                prompts = [""] * args.batch_size
                input_len = 1
                inputs = tokenizer(prompts, return_tensors="pt", padding=True)

            # batch generation
            output_sequences = model1.generate(
                input_ids=inputs['input_ids'].to(device),
                attention_mask=inputs['attention_mask'].to(device),
                max_length=input_len + seq_len,
                do_sample=True, 
                top_k=top_k, 
                top_p=1.0
            )

            texts = tokenizer.batch_decode(output_sequences, skip_special_tokens=True)
            for text in texts:
                if len(text) <= 2:
                    continue
                # perplexity of GPT2-LlaMa and GPT2-S
                p1 = calculatePerplexity(text, model1, tokenizer)
                # p2 = calculatePerplexity(text, model2, tokenizer)

                # perplexity on lower-case sample
                # p_lower = calculatePerplexity(text.lower(), model1, tokenizer)

                # Zlib "entropy" of sample
                zlib_entropy = len(zlib.compress(bytes(text, 'utf-8')))

                samples.append(text)
                scores["LlaMa"].append(p1.cpu())
                # scores["S"].append(p2.cpu())
                # scores["Lower"].append(p_lower.cpu())
                scores["zlib"].append(zlib_entropy)

            pbar.update(args.batch_size)

    scores["LlaMa"] = np.asarray(scores["LlaMa"])
    # scores["S"] = np.asarray(scores["S"])
    # scores["Lower"] = np.asarray(scores["Lower"])
    scores["zlib"] = np.asarray(scores["zlib"])

    f = open("llama-samples-perp_noprompt.txt", 'w+', encoding="utf-8")
        
    # Sort by perplexity
    metric = -np.log(scores["LlaMa"])
    print(f"======== top sample by LlaMa perplexity: ========")
    print_best(metric, samples, "PPL", scores["LlaMa"])
    utils.print_best_tofile(metric, samples, "PPL", scores["LlaMa"], f, n=1000)
    f.close()
    print()
    print()

    # Sort by ratio of log perplexities of S and LlaMa models
    # metric = np.log(scores["S"]) / np.log(scores["LlaMa"])
    # print(f"======== top sample by ratio of S and LlaMa perplexities: ========")
    # print_best(metric, samples, "PPL-LlaMa", scores["LlaMa"], "PPL-S", scores["S"])
    # print()
    # print()

    # Sort by ratio of log perplexities of lower-case and normal-case perplexities 
    # f = open("llama-samples-perp.txt", 'w+', encoding="utf-8")
    # metric = np.log(scores["Lower"]) / np.log(scores["LlaMa"])
    # print(f"======== top sample by ratio of lower-case and normal-case perplexities: ========")
    # print_best(metric, samples, "PPL-LlaMa", scores["LlaMa"], "PPL-LlaMa-Lower", scores["Lower"])
    # utils.print_best_tofile(metric, samples, "PPL-LlaMa", scores["LlaMa"], f, n=1000)
    # f.close()
    # print()
    # print()

    # Sort by ratio of Zlib entropy and LlaMa perplexity
    f = open("llama-samples-zlib_noprompt.txt", 'w+', encoding="utf-8")
    metric = scores["zlib"] / np.log(scores["LlaMa"])
    print(f"======== top sample by ratio of Zlib entropy and LlaMa perplexity: ========")
    print_best(metric, samples, "PPL-LlaMa", scores["LlaMa"], "Zlib", scores["zlib"])
    utils.print_best_tofile(metric, samples, "PPL-LlaMa", scores["LlaMa"], f, n=1000)
    f.close()

def parse_arguments(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument('--N', type=int, default=1000, help="Number of samples to generate")
    parser.add_argument('--batch-size', type=int, default=10, help="Batch size for generation")
    parser.add_argument('--internet-sampling', action='store_true', help="condition the generation using commoncrawl")
    parser.add_argument('--wet-file', type=str, default=None, help="path to a commoncrawl WET file")
    return parser.parse_args(argv)

if __name__ == '__main__':
    args = parse_arguments(sys.argv[1:])
    main()
