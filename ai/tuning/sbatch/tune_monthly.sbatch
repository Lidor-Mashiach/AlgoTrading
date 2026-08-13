#!/bin/bash
#SBATCH --partition main
#SBATCH --time 3-00:00:00
#SBATCH --job-name tune_monthly
#SBATCH --output tune_monthly-%x.out
#SBATCH --mail-user=lidorma@post.bgu.ac.il
#SBATCH --mail-type=END,FAIL
#SBATCH --gpus=0
#SBATCH --cpus-per-task=32
#SBATCH --mem=16G

echo "SLURM_JOBID"=$SLURM_JOBID
echo "SLURM_JOB_NODELIST"=$SLURM_JOB_NODELIST

module load anaconda
source activate algo_trade_env

cd ~/projects/AlgoTrade
python -u ai/tuning/tune_monthly.py 600