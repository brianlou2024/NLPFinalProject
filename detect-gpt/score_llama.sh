results_name=$(date "+%Y-%m-%d-%H-%M-%S")

python score.py \
    --dataset local \
    --n_samples 100 \
    --n_perturbation_list 10 \
    --base_model_name llama \
    --mask_filling_model_name t5-base \
    --batch_size 50 \
    --output_name $results_name \
    --skip_baselines \
    --cache_dir /home/arti/.cache \
    --dataset_path ../llama-samples.txt

python process.py \
    --results_path results/$results_name/perturbation_10_z_results.json \
    --output_path results/$results_name/sorted_samples.json
