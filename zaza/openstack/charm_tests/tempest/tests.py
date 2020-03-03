import os

import zaza
import zaza.charm_lifecycle.utils
import zaza.charm_lifecycle.test
import tempest.cmd.main
import tempfile


class TempestTest():

    test_runner = zaza.charm_lifecycle.test.DIRECT

    def run(self):
        charm_config = zaza.charm_lifecycle.utils.get_charm_config()
        tempest_options = ['run', '--config', 'tempest/etc/tempest.conf']
        for model_alias in zaza.model.get_juju_model_aliases().keys():
            tempest_test_key = model_alias
            if model_alias == zaza.charm_lifecycle.utils.DEFAULT_MODEL_ALIAS:
                tempest_test_key = 'default'
            config = charm_config['tests_options']['tempest'][tempest_test_key]
            if config.get('regex'):
                tempest_options.extend(['--regex', config.get('regex')])
            if config.get('black-regex'):
                tempest_options.extend(['--black-regex', config.get('black-regex')])
            with tempfile.TemporaryDirectory() as tmpdirname:
                if config.get('whitelist'):
                    white_file = os.path.join(tmpdirname, 'white.cfg')
                    with open(white_file, 'w') as f:
                        f.write('\n'.join(config.get('whitelist')))
                        f.write('\n')
                    tempest_options.extend(['--whitelist-file', white_file])
                if config.get('blacklist'):
                    black_file = os.path.join(tmpdirname, 'black.cfg')
                    with open(black_file, 'w') as f:
                        f.write('\n'.join(config.get('blacklist')))
                        f.write('\n')
                    tempest_options.extend(['--blacklist-file', black_file])
                print(tempest_options)
                the_app = tempest.cmd.main.Main()
                _exec_tempest = the_app.run(tempest_options)
                if not _exec_tempest:
                    return False
        return True

class TempestSmokeTest():

    test_runner = zaza.charm_lifecycle.test.DIRECT

    def run(self):
        the_app = tempest.cmd.main.Main()
        return the_app.run([
            'run',
            '--smoke',
            '--config', 'tempest/etc/tempest.conf'])
