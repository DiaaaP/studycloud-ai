resource "aws_vpc" "worker" {
  cidr_block           = "10.42.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
}

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_subnet" "worker_private" {
  count             = 2
  vpc_id            = aws_vpc.worker.id
  cidr_block        = cidrsubnet(aws_vpc.worker.cidr_block, 8, count.index + 1)
  availability_zone = data.aws_availability_zones.available.names[count.index]

  tags = {
    Name = "${local.name_prefix}-worker-private-${count.index + 1}"
  }
}

resource "aws_route_table" "worker_private" {
  vpc_id = aws_vpc.worker.id
}

resource "aws_route_table_association" "worker_private" {
  count          = length(aws_subnet.worker_private)
  subnet_id      = aws_subnet.worker_private[count.index].id
  route_table_id = aws_route_table.worker_private.id
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.worker.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.worker_private.id]
}

resource "aws_vpc_endpoint" "dynamodb" {
  vpc_id            = aws_vpc.worker.id
  service_name      = "com.amazonaws.${var.aws_region}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.worker_private.id]
}

resource "aws_security_group" "worker" {
  name        = "${local.name_prefix}-worker"
  description = "No inbound access; private document worker egresses through AWS gateway endpoints."
  vpc_id      = aws_vpc.worker.id

  egress {
    description = "HTTPS to AWS services; subnets have no internet route."
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
