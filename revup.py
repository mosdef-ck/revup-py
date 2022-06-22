import argparse
import logging
import re
import subprocess
import sys

logging.basicConfig(format="%(levelname)s: %(message)s", level=logging.INFO)
RESIM_COMMAND = "resim"
ENV_FILE = ".env"
BOOTSTRAP_FILE_NAME = "revup.rev"

ARGP = argparse.ArgumentParser()
ARGP.add_argument("-f", dest="input_file", type=str, default='revup.rev', help="input file containing revup directives to execute")
ARGP.add_argument("-e", dest="env_file", type=str, default=".env", help="the resulting env file to output variables")
ARGP.add_argument("--generate", help="generate a standard revup file", action='store_true')


def perform_variable_sub(txt: str, named_props: dict):
    for k, v in named_props.items():
        if txt.find(f"${k}") != -1:
            return txt.replace(f"${k}", v)
    return txt


class Revup:
    def __init__(self, parsed_args):
        self.parsed_args = parsed_args

    def rev(self):
        self.check_resim_is_executable()
        self.validate_args()
        # are we generating a bootstrap revup file?
        if self.parsed_args.generate:
            self.generate_revup_filesample()
        else:
            self.process_inputfile()


    def check_resim_is_executable(self):
        try:
            subprocess.run([f"{RESIM_COMMAND} --version"], check=True, shell=True, stdout=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            logging.error(f"error invoking '{RESIM_COMMAND}'. Make sure it's visible on PATH")

    def validate_args(self):
        if self.parsed_args.generate == False:
            try:
                with open(self.parsed_args.input_file, 'r'):
                    pass
            except:
                logging.error(f"'{self.parsed_args.input_file}' does not exist OR is not readable")

    def generate_revup_filesample(self):
        with open("template/bootstrap.r") as template:
            try:
                with open(BOOTSTRAP_FILE_NAME, "w+") as out:
                    out.writelines(template.readlines())
                    out.close()
                    logging.info(f"generated bootstrap file, see {BOOTSTRAP_FILE_NAME}")
            except Exception as e:
                logging.error(f"failed to generate bootstrap file due to {e}")

    def populate_named_props(self, named_props, addresses):
        named_props_map = {}
        if len(named_props) > 0:
            named_props_parts = named_props.split(" ")
            if len(named_props_parts) <= len(addresses):
                idx = 0
                for prop in named_props_parts:
                    named_props_map[prop] = addresses[idx]
                    idx += 1

        return named_props_map

    def process_inputfile(self):
        with open(self.parsed_args.input_file, 'r') as f:
            commands = f.readlines()

        named_props_map = {}

        for command in commands:
            # ignore newlines and commented out directives
            if command == "\n" or command.startswith("//") or command.startswith("\\\\"):
                continue
            # separate the command and the named properties
            command_and_args = command.split("->")
            # execute the resim command
            logging.debug(f"command parts are :{command_and_args}")
            normalized_cmd = command_and_args[0].strip().replace("\n", "")
            addresses = ResimExecutor().execute(normalized_cmd, named_props_map)
            # map addresses to properties
            if len(command_and_args) > 1:
                named_props = command_and_args[1].strip().replace("\n", "")
                named_props_map.update(self.populate_named_props(named_props, addresses))
            logging.debug(f"mapped props are {named_props_map}")

        # expose the named properties via the env file
        self.write_props_to_env(named_props_map)

    def write_props_to_env(self, named_props_map):

        try:
            with open(ENV_FILE, "w") as env_file:
                for (k, v) in named_props_map.items():
                    env_file.write(f"{k}={v}\n")
        except Exception as e:
            logging.error(f"failed to write to env file due to {e}")


class ResimExecutor:
    def __init__(self):
        # resim command output will have addresses in this format
        self.address_extract_patterns = [
            re.compile(r"component: ([0-9a-fA-F]+)", re.IGNORECASE),
            re.compile(r"resource: ([0-9a-fA-F]+)", re.IGNORECASE),
            re.compile(r"package: ([0-9a-fA-F]+)", re.IGNORECASE),
            re.compile(r"account component address: ([0-9a-fA-F]+)", re.IGNORECASE),
            re.compile(r"public key: ([0-9a-fA-F]+)", re.IGNORECASE),
        ]

    def execute(self, cmd: str, named_props: dict):
        logging.debug(f"executing '{RESIM_COMMAND} {cmd}'")
        if re.search(r"run .+(\w+\.rtm)", cmd):
            logging.debug("Running manifest")
            self.do_run_manifest(cmd, named_props)
        else:
            try:
                normalized_cmd = perform_variable_sub(cmd, named_props)
                normalized_cmd = [RESIM_COMMAND] + normalized_cmd.split(" ")
                logging.info(f">>> {cmd}")
                output = subprocess.run(normalized_cmd, capture_output=True, check=True).stdout
                cmd_output = output.splitlines()
                output_addresses = self.extract_output_addresses(cmd_output)
                logging.debug(f"output_addresses are {output_addresses}")
                return output_addresses
            except subprocess.CalledProcessError as e:
                logging.error(f"failed to execute '{RESIM_COMMAND} {cmd}' due to {e.stderr}")

        return {}

    def extract_output_addresses(self, cmd_output: list):
        addresses = []
        for line in cmd_output:
            for p in self.address_extract_patterns:
                match = re.search(p, str(line))
                if match:
                    addresses.append(match.group(1))

        return addresses

    def do_run_manifest(self, cmd, named_props: dict):
        tx_file_pat = re.compile(r"(\w+\.rtm)", re.IGNORECASE)
        file_name_match = re.search(tx_file_pat, cmd)
        if file_name_match:
            file_name = file_name_match.group(1)
            try:
                updated_content = []
                with open(file_name, 'r') as tx_file:
                    rtm_content = tx_file.readlines()

                    if len(rtm_content) > 0:
                        for line in rtm_content:
                            normalized_line = str(line)
                            for k, v in named_props.items():
                                normalized_line = normalized_line.replace(f"${k}", v)
                            updated_content.append(normalized_line)
                if len(updated_content) > 0:
                    with open(f"{file_name_match.group(1)}.dat", 'w') as out:
                        out.writelines(updated_content)

            except Exception as e:
                logging.error(f"failed to process manifest file due to {e}")


def main(args):
    args = ARGP.parse_args(args)
    logging.debug(f"parsed arguments: {args}")
    Revup(args).rev()


if __name__ == "__main__":
    main(sys.argv[1:])
