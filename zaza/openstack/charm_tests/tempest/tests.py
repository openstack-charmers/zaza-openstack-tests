import zaza.charm_lifecycle.test
import tempest.cmd.main


class TempestTest():

    test_runner = zaza.charm_lifecycle.test.DIRECT

    def run(self):
        the_app = tempest.cmd.main.Main()
        return the_app.run([
            'run',
            '--smoke',
            '--config', 'tempest/etc/tempest.conf'])
