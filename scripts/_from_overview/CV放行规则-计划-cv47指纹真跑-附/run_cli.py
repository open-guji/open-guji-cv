import sys
wt=sys.argv[1]; sys.path.insert(0,wt)
import open_guji_cv
assert open_guji_cv.__file__.startswith(wt),open_guji_cv.__file__
from open_guji_cv.cli_v2 import main
sys.argv=["guji"]+sys.argv[2:]
main()
