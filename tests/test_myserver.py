"""Unit and integration test suite for myserver v2.22.0."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from myserver.core import paths, helpers
from myserver.services import nginx, php, redis
from myserver.features import vhost


class TestMyServerSuite(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="myserver-test-"))
        self.orig_prefix = paths.PREFIX
        self.orig_home = paths.HOME
        self.orig_nginx_dir = paths.NGINX_DIR
        self.orig_nginx_conf = paths.NGINX_CONF
        self.orig_nginx_confd = paths.NGINX_CONFD_DIR
        self.orig_live_conf = paths.LIVE_CONF_FILE
        self.orig_ssl_dir = paths.SSL_DIR
        self.orig_default_cert = paths.DEFAULT_CERT
        self.orig_default_key = paths.DEFAULT_KEY
        self.orig_php_fpm_dir = paths.PHP_FPM_DIR
        self.orig_php_fpm_conf = paths.PHP_FPM_CONF
        self.orig_php_confd = paths.PHP_CONFD_DIR
        self.orig_php_myserver_ini = paths.PHP_MYSERVER_INI
        self.orig_log_dir = paths.LOG_DIR
        self.orig_tmp_dir = paths.TMP_DIR
        self.orig_htdocs = paths.HTDOCS_DIR
        self.orig_home_backup = paths.HOME_BACKUP_DIR
        self.orig_storage_backup = paths.STORAGE_BACKUP_DIR
        self.orig_redis_conf = paths.REDIS_CONF
        self.orig_redis_disabled = paths.REDIS_DISABLED_FILE

        # Point paths to temporary sandbox
        paths.PREFIX = self.tmp_dir / "usr"
        paths.HOME = self.tmp_dir / "home"
        paths.HOME.mkdir(parents=True, exist_ok=True)
        paths.NGINX_DIR = paths.PREFIX / "etc/nginx"
        paths.NGINX_CONF = paths.NGINX_DIR / "nginx.conf"
        paths.NGINX_CONFD_DIR = paths.NGINX_DIR / "conf.d"
        paths.LIVE_CONF_FILE = paths.NGINX_DIR / "live-reload.conf"
        paths.SSL_DIR = paths.NGINX_DIR / "ssl"
        paths.DEFAULT_CERT = paths.SSL_DIR / "server.crt"
        paths.DEFAULT_KEY = paths.SSL_DIR / "server.key"
        paths.PHP_FPM_DIR = paths.PREFIX / "etc/php-fpm.d"
        paths.PHP_FPM_CONF = paths.PHP_FPM_DIR / "www.conf"
        paths.PHP_CONFD_DIR = paths.PREFIX / "etc/php/conf.d"
        paths.PHP_MYSERVER_INI = paths.PHP_CONFD_DIR / "99-myserver.ini"
        paths.LOG_DIR = paths.PREFIX / "var/log"
        paths.TMP_DIR = paths.PREFIX / "tmp"
        paths.HTDOCS_DIR = paths.HOME / "htdocs"
        paths.HOME_BACKUP_DIR = paths.HOME / "myserver-backups"
        paths.STORAGE_BACKUP_DIR = paths.HOME / "storage/shared/myserver-backups"
        paths.REDIS_CONF = paths.PREFIX / "etc/redis.conf"
        paths.REDIS_DISABLED_FILE = paths.PREFIX / "etc/myserver_disable_redis"

    def tearDown(self):
        paths.PREFIX = self.orig_prefix
        paths.HOME = self.orig_home
        paths.NGINX_DIR = self.orig_nginx_dir
        paths.NGINX_CONF = self.orig_nginx_conf
        paths.NGINX_CONFD_DIR = self.orig_nginx_confd
        paths.LIVE_CONF_FILE = self.orig_live_conf
        paths.SSL_DIR = self.orig_ssl_dir
        paths.DEFAULT_CERT = self.orig_default_cert
        paths.DEFAULT_KEY = self.orig_default_key
        paths.PHP_FPM_DIR = self.orig_php_fpm_dir
        paths.PHP_FPM_CONF = self.orig_php_fpm_conf
        paths.PHP_CONFD_DIR = self.orig_php_confd
        paths.PHP_MYSERVER_INI = self.orig_php_myserver_ini
        paths.LOG_DIR = self.orig_log_dir
        paths.TMP_DIR = self.orig_tmp_dir
        paths.HTDOCS_DIR = self.orig_htdocs
        paths.HOME_BACKUP_DIR = self.orig_home_backup
        paths.STORAGE_BACKUP_DIR = self.orig_storage_backup
        paths.REDIS_CONF = self.orig_redis_conf
        paths.REDIS_DISABLED_FILE = self.orig_redis_disabled
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_identifier_validation_blocks_injections(self):
        self.assertTrue(helpers.is_safe_identifier("laravel_app-01"))
        self.assertFalse(helpers.is_safe_identifier(""))
        self.assertFalse(helpers.is_safe_identifier("app; rm -rf /"))
        self.assertFalse(helpers.is_safe_identifier("db`id`"))
        self.assertFalse(helpers.is_safe_identifier("../etc/passwd"))
        self.assertFalse(helpers.is_safe_identifier("my project"))

    def test_semver_comparison_prevents_downgrade(self):
        self.assertTrue(helpers.is_newer_version("2.21.4", "2.22.0"))
        self.assertTrue(helpers.is_newer_version("2.22.0", "2.22.1"))
        self.assertFalse(helpers.is_newer_version("2.22.0", "2.22.0"))
        self.assertFalse(helpers.is_newer_version("2.22.0", "2.21.4"))

    def test_safe_backup_dir_resolution(self):
        paths.resolve_runtime_paths()
        self.assertEqual(paths.BACKUP_DIR, paths.HOME_BACKUP_DIR)
        self.assertFalse((paths.HOME / "storage").exists())

        (paths.HOME / "storage/shared").mkdir(parents=True, exist_ok=True)
        paths.resolve_runtime_paths()
        self.assertEqual(paths.BACKUP_DIR, paths.STORAGE_BACKUP_DIR)

    def test_nginx_config_android_and_tunnel_hardening(self):
        self.assertTrue(nginx.setup(paths.HTDOCS_DIR))
        conf = paths.NGINX_CONF.read_text()
        self.assertIn("worker_processes 1;", conf)
        self.assertIn("if ($http_cf_connecting_ip != \"\")", conf)
        self.assertIn("return 403;", conf)
        self.assertIn(f"include {paths.NGINX_CONFD_DIR}/*.conf;", conf)

    def test_php_fpm_ondemand_and_confd_isolation(self):
        self.assertTrue(php.setup_fpm())
        fpm_txt = paths.PHP_FPM_CONF.read_text()
        self.assertIn("pm = ondemand", fpm_txt)
        self.assertIn("pm.max_children = 4", fpm_txt)

        self.assertTrue(php.create_php_ini())
        self.assertTrue(paths.PHP_MYSERVER_INI.exists())
        ini_txt = paths.PHP_MYSERVER_INI.read_text()
        self.assertIn("memory_limit = 256M", ini_txt)

    def test_vhost_lifecycle(self):
        ok = vhost.add_site("shop", project_path=paths.HTDOCS_DIR / "shop", port=8085, site_type="laravel")
        self.assertTrue(ok)
        sites = vhost.list_sites()
        self.assertEqual(len(sites), 1)
        self.assertEqual(sites[0]["name"], "shop")
        self.assertEqual(sites[0]["port"], "8085")
        self.assertEqual(sites[0]["type"], "laravel")
        self.assertTrue(vhost.remove_site("shop"))
        self.assertEqual(len(vhost.list_sites()), 0)

    def test_android_process_counter_and_redis_toggle(self):
        count, rss = helpers.count_user_processes()
        self.assertGreaterEqual(count, 1)
        self.assertGreaterEqual(rss, 0.0)

        self.assertTrue(redis.is_enabled())
        redis.set_enabled(False)
        self.assertFalse(redis.is_enabled())
        redis.set_enabled(True)
        self.assertTrue(redis.is_enabled())

    def test_zombie_reaping_and_safe_stop_for_popen_children(self):
        """Simulate starting mariadbd/cloudflared inside the menu via Popen
        without calling proc.wait(), then stopping them via safe_stop()."""
        dummy_script = self.tmp_dir / "fake-mariadbd-daemon"
        dummy_script.write_text("#!/bin/sh\nsleep 30\n")
        dummy_script.chmod(0o755)
        pid_file = self.tmp_dir / "fake.pid"

        proc = subprocess.Popen(
            [str(dummy_script)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        helpers.write_pid_file(pid_file, proc.pid)
        time.sleep(0.1)

        self.assertTrue(helpers.is_process_running("fake-mariadbd-daemon", pid_file=pid_file))
        stopped = helpers.safe_stop(pid_file, ("fake-mariadbd-daemon",), grace=1.5)
        self.assertTrue(stopped)
        self.assertFalse(helpers.pid_alive(proc.pid))
        self.assertFalse(helpers.is_process_running("fake-mariadbd-daemon", pid_file=pid_file))

    def test_i18n_removed_english_only(self):
        i18n_dir = Path(__file__).resolve().parent.parent / "myserver" / "i18n"
        self.assertFalse(i18n_dir.exists())


if __name__ == "__main__":
    unittest.main()
