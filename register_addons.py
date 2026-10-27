import argparse,json
from l4d2_converter.registration import register_installed_addons
if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Register installed Leave 2 Loader addon folders without changing existing enabled states.')
    parser.add_argument('--game',required=True,help='Xbox game root or its left4dead2 folder; restart the game afterward')
    args=parser.parse_args();print(json.dumps(register_installed_addons(args.game),indent=2))
