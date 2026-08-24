import multiprocessing as mp
mp.set_start_method("fork", force=True)
import sys
sys.argv = ["analyze_repos", "--aggregation=month"]
from scripts import analyze_repos
analyze_repos.main()
