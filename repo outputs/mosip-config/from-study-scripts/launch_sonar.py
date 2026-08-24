import multiprocessing as mp
mp.set_start_method("fork", force=True)   # match the Linux behavior the script assumes
import sys
sys.argv = ["run_sonarqube", "--aggregation=month"]
from scripts import run_sonarqube
run_sonarqube.main()
