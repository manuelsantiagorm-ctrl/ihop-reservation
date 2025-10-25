def test_admin_mx_no_ve_ar(client, admin_mx, suc_mx, suc_ar, django_assert_num_queries):
    client.force_login(admin_mx)
    resp = client.get(reverse("staff_sucursales"))
    html = resp.content.decode()
    assert suc_mx.nombre in html
    assert suc_ar.nombre not in html

    url = reverse("admin_mapa_sucursal", args=[suc_ar.id])
    assert client.get(url).status_code in (403, 404)
